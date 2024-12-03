from .models import TrialModel, DrugModel
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Body, HTTPException, Request, status, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from typing import Optional, List
import re

trial_router = APIRouter()
drug_router = APIRouter()

client = OpenAI(
    # Defaults to os.environ.get("OPENAI_API_KEY")
    # TODO: change base URL for Radiant
)

trial_project = {
    '$project': {
        '_id': 0,
        'nct_id': 1,
        'brief_title': 1,
        'official_title': 1,
        'start_date': 1,
        'completion_date': 1,
        'condition': 1,
        'intervention': 1,
        'intervention_mesh_term': 1,
        'sponsors': 1,
        'status': 1,
        'phase': 1,
        #'highlights': 1,
        'score': 1,
        'trial_pagination_token': 1,
        'count': 1
    }
}

trial_autocomplete_project = {
    '$project': {
        '_id': 0,
        'nct_id': 1,
        'brief_title': 1,
        'highlights': { '$meta': 'searchHighlights' },
    }
}

fuzzy = {
    'maxEdits': 2,
    'maxExpansions': 100
}

@trial_router.get("/", response_description="List all trials")
async def list_trials(
    request: Request,
    limit: Optional[int] = 100,
    skip: Optional[int] = 0,
    pagination_token: Optional[str] = None,
    sort: Optional[str] = None,
    sort_order: Optional[int] = 1):

    trials = await search_trials(
        request,
        limit=limit,
        skip=skip,
        sort=sort,
        sort_order=sort_order,
        pagination_token=pagination_token,
        filters=None)
    return trials

@trial_router.get("/{nct_id}", response_description="Get a single trial")
async def show_trial(nct_id: str, request: Request):
    project = trial_project['$project']
    project['completion_date'] = 1
    project['detailed_description'] = 1
    project['enrollment'] = 1
    project['gender'] = 1
    project['maximum_age'] = 1
    project['minimum_age'] = 1
    project['facility'] = 1

    if (trial := await request.app.mongodb["trials"].find_one(
        {"nct_id": nct_id}, project)) is not None:
        return trial

    raise HTTPException(status_code=404, detail=f"Trial {nct_id} not found")

@trial_router.post("/autocomplete", response_description="Autocomplete search for trials")
async def autocomplete_trials(
    request: Request,
    term: str,
    limit: Optional[int] = 5,
    skip: Optional[int] = 0):

    nct_re = re.compile(r'^NCT\d{1,8}$', re.IGNORECASE)
    nct_match = nct_re.match(term) if term else None
    nct = nct_match.group(0) if nct_match else None
    print(f"nct: {nct}")
  
    autocomplete_search  = {
        '$search': {
            'index': 'default',
                'autocomplete': {
                    'path': 'nct_id' if nct else 'brief_title',
                    'query': nct if nct else term
            },
            'highlight': {
                'path': 'nct_id' if nct else 'brief_title'
            }
        }
    }
  
    title_override = {
        '$addFields': {
            'nct_title': { '$concat': ['$nct_id', ': ', '$brief_title'] }
        }
    }
  
    pipeline = [
        autocomplete_search,
        {
            '$addFields': {
                'score': { '$meta': 'searchScore' },
            }
        }, {
            '$skip': skip
        }, {
            '$limit': limit
        },
        trial_autocomplete_project
    ]
  
    if nct:
        pipeline.append(title_override)
  
    trials = await request.app.mongodb["trials"].aggregate(pipeline).to_list(length=limit)
    return trials

@trial_router.post("/", response_description="Search for trials")
async def search_trials(
    request: Request,
    term: Optional[str] = None,
    limit: Optional[int] = 100,
    skip: Optional[int] = 0,
    pagination_token: Optional[str] = None,
    sort: Optional[str] = None,
    sort_order: Optional[int] = 1,
    use_vector: Optional[bool] = False,
    num_candidates: Optional[int] = 1000,
    filters: Optional[List[str]] = Query(None)):
    basic_search_no_term = {
        '$search': {
            'index': 'default',
            'compound': {
                'filter': [{
                    'exists': { 'path': 'nct_id' }
                }]
            },
            'count': { 'type': 'total' }
        }
    }

    basic_search = {
        '$search': {
            'index': 'default',
            'compound': {
                'filter': [{
                    'exists': { 'path': 'nct_id' }
                }],
                'must': [{
                    'text': {
                        'query': term,
                        'path': [
                            'brief_title',
                            'official_title',
                            'brief_summary',
                            'detailed_description'
                        ],
                        'fuzzy': fuzzy
                    }
                }]
            },
            'count': { 'type': 'total' },
            #'highlight': {
            #    'path': [
            #        'brief_summary',
            #        'detailed_description'
            #    ]
            #},
            'tracking': { 'searchTerms': term }
        }
    }

    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)
    
    search_with_filters = {
        '$search': {
            'index': 'default',
            'compound': {
                'must': [{
                    'text': {
                        'query': term,
                        'path': [
                            'brief_title',
                            'official_title',
                            'brief_summary',
                            'detailed_description'
                        ],
                        'fuzzy': fuzzy
                    }
                }],
                'filter': [{
                    'queryString': {
                        'defaultPath': default_filter_field,
                        'query': query_string
                    }
                }]
            },
            'count': { 'type': 'total' },
            #'highlight': {
                #'path': [
                    #'brief_summary',
                    #'brief_title',
                    #'official_title',
                    #'detailed_description'
                #]
            #},
            'tracking': { 'searchTerms': term }
        }
    }
    
    search_no_term_with_filters = {
        '$search': {
            'index': 'default',
            'compound': {
                'filter': [{
                    'queryString': {
                        'defaultPath': default_filter_field,
                        'query': query_string
                    }
                }]
            },
            'count': { 'type': 'total' },
            'tracking': { 'searchTerms': query_string }
        }
    }
    
    vector_search = {
        '$vectorSearch': {
            'index': 'trials_vector_index', 
            'queryVector': [],
            'path': 'detailed_description_vector', 
            'numCandidates': num_candidates,
            'limit': limit
        }
    }

    add_fields = {
        '$addFields': {
            'score': {'$meta': 'searchScore'},
            #'highlights': {'$meta': 'searchHighlights'},
            'trial_pagination_token': {'$meta' : 'searchSequenceToken'},
        }
    }

    range_query = await filters_to_range_query(filters, use_vector)
    if (range_query != None):
        basic_search['$search']['compound']['filter'].append(range_query)
        basic_search_no_term['$search']['compound']['filter'].append(range_query)
        search_no_term_with_filters['$search']['compound']['filter'].append(range_query)
        search_with_filters['$search']['compound']['filter'].append(range_query)
        vector_search['$vectorSearch']['filter'] = range_query
    
    if (use_vector == True):
        if (term is None):
            raise HTTPException(status_code=422)
        else:
            add_fields['$addFields']['score'] = { '$meta': 'vectorSearchScore' }
    else:
        add_fields['$addFields']['count'] = '$$SEARCH_META.count'
    
    pipeline = []
    
    if (term is None):
        if query_string != None and len(query_string) > 0:
            pipeline.append(search_no_term_with_filters)
        else:
            pipeline.append(basic_search_no_term)
    else:
        if (use_vector == True):
            # vectorize the search term
            vector_search['$vectorSearch']['queryVector'] = await create_embeddings(term) #create_openai_embeddings(term, client)
            pipeline.append(vector_search)
        else:
            if query_string != None and len(query_string) > 0:
                pipeline.append(search_with_filters)
            else:
                pipeline.append(basic_search)
            pipeline.append({'$limit': limit})
    
    # sorting
    if (sort != None and use_vector == False):
        pipeline[0]['$search']['sort'] = { sort: sort_order }
    
    # pagination
    if pagination_token != None:
        pipeline[0]['$search']['searchAfter'] = pagination_token
    elif skip and skip > 0:
        pipeline.append({'$skip': skip})

    pipeline.extend([add_fields, trial_project])
    print(pipeline)

    trials = await request.app.mongodb["trials"].aggregate(pipeline).to_list(length=limit)

    return trials

@trial_router.post("/facets", response_description="Facet search for trials")
async def search_trial_facets(
    request: Request,
    term: Optional[str] = None,
    filters: Optional[List[str]] = Query(None),
    count_only: Optional[bool] = False,
    use_vector: Optional[bool] = False):
    
    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)
    range_query = await filters_to_range_query(filters, use_vector)

    count_all_facets = {
        '$searchMeta': {
            'index': 'default',
            'exists': { 'path': 'nct_id' },
            'count': { 'type': 'total' },
        }
    }

    count_facets_with_filters = {
        '$searchMeta': {
            'compound': {
                'filter': [{
                    'queryString': {
                        'defaultPath': default_filter_field,
                        'query': query_string
                    }
                }]
            },
            'count': { 'type': 'total' }
        }
    }

    facets_object = {
        'conditions': {
            'type': 'string',
            'path': 'condition',
            'numBuckets': 10
        },
        'intervention_types': {
            'type': 'string',
            'path': 'intervention',
            'numBuckets': 10
        },
        'interventions': {
            'type': 'string',
            'path': 'intervention_mesh_term',
            'numBuckets': 10
        },
        'genders': {
            'type': 'string',
            'path': 'gender',
            'numBuckets': 10
        },
        'sponsors': {
            'type': 'string',
            'path': 'sponsors.agency',
            'numBuckets': 10
        },
        'start_date': {
            'type': 'date',
            'path': 'start_date',
            'boundaries': [
                datetime.fromisoformat('2012-01-01'),
                datetime.fromisoformat('2013-01-01'),
                datetime.fromisoformat('2014-01-01'),
                datetime.fromisoformat('2015-01-01'),
                datetime.fromisoformat('2016-01-01'),
                datetime.fromisoformat('2017-01-01'),
                datetime.fromisoformat('2018-01-01'),
                datetime.fromisoformat('2019-01-01'),
                datetime.fromisoformat('2020-01-01'),
                datetime.fromisoformat('2021-01-01'),
                datetime.fromisoformat('2022-01-01'),
                datetime.fromisoformat('2023-01-01'),
                datetime.fromisoformat('2024-01-01'),
            ],
            'default': 'other'
        }
    }

    basic_facets_no_term = {
        '$searchMeta': {
            'index': 'default',
            'facet': {
                'facets': facets_object
            }
        }
    }

    compound_operator = { 'compound': {} }

    if query_string and len(query_string) > 0:
        compound_operator.compound.filter = [{
            'queryString': {
                'defaultPath': default_filter_field,
                'query': query_string
            }
        }]

    if term and len(term) > 0:
        compound_operator.compound.must = [{
            'text': {
                'query': term,
                'path': [
                    'brief_title',
                    'official_title',
                    'brief_summary',
                    'detailed_description'
                ]
            }
        }]

    if range_query:
        if compound_operator.compound.filter and len(compound_operator.compound.filter) > 0:
            compound_operator.compound.filter.append(range_query)
        else:
            compound_operator.compound.filter = [range_query]

    search_facets_with_filters = {
        '$searchMeta': {
            'index': 'default',
            'facet': {
                'operator': compound_operator,
                'facets': facets_object
            }
        }
    }

    add_dields = {
        '$addFields': { 'count': '$$SEARCH_META.count' }
    }

    pipeline = []

    if count_only:
        if query_string and len(query_string.strip()) > 0:
            # filters provided
            print("count only: filters provided")
            pipeline.append(count_facets_with_filters)
        else:
            # no filters provided
            print("count only: no filters provided")
            pipeline.append(count_all_facets)
    elif term and len(term.strip()) > 0:
        # search term provided
        # TODO: add vector support for facets
        print("not count only: use search facets")
        pipeline.append(search_facets_with_filters)
    elif query_string and len(query_string.strip()) > 0:
        print("not count only *")
        # filters provided
        pipeline.append(search_facets_with_filters)
    else:
        print("not count only basic");
        # no search term or filters provided
        pipeline.append(basic_facets_no_term)

    #print(pipeline)

    facets = await request.app.mongodb["trials"].aggregate(pipeline).to_list()

    if not count_only:
        # reformat for easier consumption
        buckets = facets[0]['facet']['conditions']['buckets']
        conditions = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))
    
        buckets = facets[0]['facet']['intervention_types']['buckets']
        intervention_types = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))

        buckets = facets[0]['facet']['interventions']['buckets']
        interventions = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))

        buckets = facets[0]['facet']['sponsors']['buckets']
        sponsors = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))

        buckets = facets[0]['facet']['genders']['buckets']
        genders = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))

        buckets = facets[0]['facet']['start_date']['buckets']
        sdates = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))
  
        facets[0]['conditions'] = conditions
        facets[0]['intervention_types'] = intervention_types
        facets[0]['interventions'] = interventions
        facets[0]['sponsors'] = sponsors
        facets[0]['genders'] = genders
        facets[0]['start_date'] = sdates
        del facets[0]['facet']

    return facets

async def create_embeddings(text: str):
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return model.encode(text).tolist()

async def create_openai_embeddings(text: str, client: OpenAI):
    response = client.embeddings.create(
        model= "text-embedding-ada-002",
        input=[text]
    )
    
    return response.data[0].embedding

async def filters_to_range_query(filters: List[str], use_vector: bool):
    '''
    Converts an array of key:value filter expressions to a range 
     <https://www.mongodb.com/docs/atlas/atlas-search/range/> query
     or a vector search pre-filter expression
     <https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#atlas-vector-search-pre-filter>
    '''

    if (filters == None or len(filters) == 0):
        return None

    date_filters = [x for x in filters if x.startswith("start_date:")]
    start_date = end_date = None
    if len(date_filters) > 0:
        parts = date_filters[0].split(":")
        p0 = parts[0]
        p1 = parts[1]
        if p1 != None and p1.startswith("\""):
            p1 = p1[1:11]
        else:
            p1 = p1[0:10]
        start_date = datetime.strptime(p1, "%Y-%m-%d")
        end_date = start_date + timedelta(days=365)
    else:
        return None

    range_query = {}
    if use_vector == True:
        range_query['$and'] = [{
            'start_date': {
                '$gte': start_date
            }
        }, {
            'start_date': {
                '$lte': end_date
            }
        }]
    else:
        range_query['range'] = {
            'path': 'start_date',
            'gte': start_date,
            'lt': end_date
        }
       
    return range_query

async def filters_to_query_string(filters: List[str]):
    '''
    Converts an array of key:value filter expressions to an Atlas Search queryString
     <https://www.mongodb.com/docs/atlas/atlas-search/queryString/> operator
    '''

    if filters == None or len(filters) == 0:
        return None

    # skip date fields
    filters_no_dates = list(filter(lambda x: not x.startswith("start_date:"), filters))
    if len(filters) == 1:
        return filters_no_dates[0]
    else:
        joined = ') AND ('.join(filters_no_dates)
        return f'({joined})'

###############
# Drug Router #
###############
drug_project = {
    '$project': {
        '_id': 0,
        'active_ingredient': 1,
        'brand_name': 1,
        'effective_time': 1,
        'highlights': 1,
        'id': 1,
        'indications_and_usage': 1,
        'purpose': 1,
        'openfda.brand_name': 1,
        'openfda.generic_name': 1,
        'openfda.manufacturer_name': 1,
        'trial_pagination_token': 1,
    }
}

drug_autocomplete_project = {
    '$project': {
        '_id': 0,
        'id': 1,
        'highlights': {'$meta': 'searchHighlights'},
        'brand_name': '$openfda.brand_name',
    }
}

@drug_router.get("/", response_description="List all drugs")
async def list_drugs(
    request: Request,
    limit: Optional[int] = 100,
    skip: Optional[int] = None,
    pagination_token: Optional[str] = None,
    sort: Optional[str] = None,
    sort_order: Optional[int] = 1):

    drugs = await search_drugs(
        request,
        limit=limit,
        skip=skip,
        pagination_token=pagination_token,
        sort=sort,
        sort_order=sort_order,
        filters=None)
    return drugs

@drug_router.get("/{uuid}", response_description="Get a single drug")
async def show_drug(uuid: str, request: Request):
    if (drug := await request.app.mongodb["drug_data"].find_one({"id": uuid}, {'_id': 0})) is not None:
        return drug

    raise HTTPException(status_code=404, detail=f"Drug {uuid} not found")

@drug_router.post("/", response_description="Search for drugs")
async def search_drugs(
    request: Request,
    term: Optional[str] = None,
    limit: Optional[int] = 100,
    skip: Optional[int] = 0,
    sort: Optional[str] = None,
    sort_order: Optional[int] = None,
    pagination_token: Optional[str] = None,
    filters: Optional[List[str]] = Query(None)):
    
    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)

    basic_search_no_term = {
        '$search': {
            'index': 'drugs',
            'compound': {
                'filter': [{
                    'exists': { 'path': 'id' }
                }]
            },
            'count': { 'type': 'total' }
        }
    }
  
    basic_search = {
        '$search': {
            'index': 'drugs',
            'compound': {
                'must': [{
                    'text': {
                        'query': term,
                        'path': [
                            'openfda.brand_name',
                            'openfda.generic_name',
                            'openfda.manufacturer_name'
                        ],
                        'fuzzy': fuzzy,
                    }
                }]
            },
            'count': { 'type': 'total' },
            'highlight': {
                'path': [
                    'openfda.brand_name',
                    'openfda.generic_name',
                    'openfda.manufacturer_name'
                ]
            },
            'tracking': { "searchTerms": term }
        }
    }
  
    search_with_filters = {
        '$search': {
            'index': 'drugs',
            'compound': {
                'must': [{
                    'text': {
                    'query': term,
                    'path': [
                        'openfda.brand_name',
                        'openfda.generic_name',
                        'openfda.manufacturer_name'
                    ],
                    'fuzzy': fuzzy
                }
            }],
            'filter': [{
                'queryString': {
                    'defaultPath': default_filter_field,
                    'query': query_string
                }
            }]
        },
            'count': { 'type': 'total' },
            'highlight': {
                'path': [
                    'openfda.brand_name', 
                    'openfda.generic_name', 
                    'openfda.manufacturer_name'
                ]
            },
            'tracking': { 'searchTerms': term }
        }
    }

    search_no_term_with_filters = {
        '$search': {
            'index': 'drugs',
            'compound': {
                'filter': [{
                    'queryString': {
                        'defaultPath': default_filter_field,
                        'query': query_string
                    }
                }]
            },
            'count': { 'type': 'total' },
        },
        'tracking': { 'searchTerms': term }
    }

    add_fields = {
        '$addFields': {
            'score': {'$meta': 'searchScore'},
            'highlights': {'$meta': 'searchHighlights'},
            'trial_pagination_token': {'$meta' : 'searchSequenceToken'},
            'count': "$$SEARCH_META.count"
        }
    }
    
    pipeline = []
    
    if (term is None):
        if query_string != None and len(query_string) > 0:
            pipeline.append(search_no_term_with_filters)
        else:
            pipeline.append(basic_search_no_term)
    else:
        if query_string != None and len(query_string) > 0:
            pipeline.append(search_with_filters)
        else:
            pipeline.append(basic_search)

    # sorting
    if (sort != None):
        sort_order = 1 if sort_order == None else sort_order
        pipeline[0]['$search']['sort'] = { sort: sort_order }

    # pagination
    if pagination_token != None:
        pipeline[0]['$search']['searchAfter'] = pagination_token
    elif skip and skip > 0:
        pipeline.append({'$skip': skip})
        
    pipeline.extend([{'$limit': limit}, add_fields, drug_project])
    #print(pipeline)

    drugs = await request.app.mongodb["drug_data"].aggregate(pipeline).to_list(length=limit)

    return drugs

@drug_router.post("/autocomplete", response_description="Autocomplete search for drugs")
async def autocomplete_drugs(
    request: Request,
    term: str,
    limit: Optional[int] = 5,
    skip: Optional[int] = 0):
      
    autocomplete_search  = {
        '$search': {
            'index': 'drugs',
            'autocomplete': {
                'path': 'openfda.brand_name',
                'query': term
            },
            'highlight': { 'path': 'openfda.brand_name' }
        }
    }
    
    pipeline = [
        autocomplete_search,
        {
            '$addFields': { 'score': { '$meta': 'searchScore' } }
        }, {
            '$skip': skip
        }, {
            '$limit': limit
        },
        drug_autocomplete_project]

    trials = await request.app.mongodb["drug_data"].aggregate(pipeline).to_list(length=limit)
    return trials

from .models import TrialModel, DrugModel, MLTModel
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

mlt_trial_project = {
    '$project': {
        '_id': 0,
        'nct_id': 1,
        'brief_title': 1,
        'start_date': 1,
        'completion_date': 1,
        'score': 1,
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

################
# Trial Router #
################
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
    project['url'] = 1
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
    #print(f"nct: {nct}")
  
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
                'should': [{
                    'text': {
                        'query': term,
                        'path': [
                            'brief_title',
                        ],
                        'score': { 'boost': { 'value': 3 } }
                    }}
                ],
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
            'count': { 'type': 'total' }
            #'highlight': {
            #    'path': [
            #        'brief_summary',
            #        'detailed_description'
            #    ]
            #}
        }
    }

    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)
    print(f"query_string: {query_string}")
    
    search_with_filters = {
        '$search': {
            'index': 'default',
            'compound': {
                'should': [{
                    'text': {
                        'query': term,
                        'path': [
                            'brief_title',
                        ],
                        'score': { 'boost': { 'value': 3 } }
                    }}
                ],
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
            #}
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
            'count': { 'type': 'total' }
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

    range_query = await filters_to_range_query(filters)
    mql_filter = await filters_to_mql_query(filters)
    print(f"mql_filter: {mql_filter}")
    if (range_query != None):
        basic_search['$search']['compound']['filter'].append(range_query)
        basic_search_no_term['$search']['compound']['filter'].append(range_query)
        search_no_term_with_filters['$search']['compound']['filter'].append(range_query)
        search_with_filters['$search']['compound']['filter'].append(range_query)
        vector_search['$vectorSearch']['filter'] = mql_filter
    
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
            vector_search['$vectorSearch']['queryVector'] = await get_cached_embeddings(request, term) #create_openai_embeddings(term, client)
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
    #print(pipeline)

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
    range_query = await filters_to_range_query(filters)

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
        },
        'statuses': {
            'type': 'string',
            'path': 'status',
            'numBuckets': 10
        },
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
        compound_operator['compound']['filter'] = [{
            'queryString': {
                'defaultPath': default_filter_field,
                'query': query_string
            }
        }]

    if term and len(term.strip()) > 0:
        compound_operator['compound']['must'] = [{
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
        print(f"compound_operator: {compound_operator}")
        if compound_operator['compound'] and compound_operator['compound']['filter'] and len(compound_operator['compound']['filter']) > 0:
            compound_operator['compound']['filter'].append(range_query)
        else:
            compound_operator['compound']['filter'] = [range_query]

    search_facets_with_filters = {
        '$searchMeta': {
            'index': 'default',
            'facet': {
                'operator': compound_operator,
                'facets': facets_object
            }
        }
    }

    pipeline = []

    if count_only:
        if query_string and len(query_string.strip()) > 0:
            # filters provided
            #print("count only: filters provided")
            pipeline.append(count_facets_with_filters)
        else:
            # no filters provided
            #print("count only: no filters provided")
            pipeline.append(count_all_facets)
    elif term and len(term.strip()) > 0:
        # search term provided
        # TODO: add vector support for facets
        #print("not count only: use search facets")
        pipeline.append(search_facets_with_filters)
    elif query_string and len(query_string.strip()) > 0:
        #print("not count only *")
        # filters provided
        pipeline.append(search_facets_with_filters)
    else:
        print("not count only basic");
        # no search term or filters provided
        pipeline.append(basic_facets_no_term)

    print(f"Facet pipeline:", pipeline)

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
  
        buckets = facets[0]['facet']['statuses']['buckets']
        statuses = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))

        facets[0]['conditions'] = conditions
        facets[0]['intervention_types'] = intervention_types
        facets[0]['interventions'] = interventions
        facets[0]['sponsors'] = sponsors
        facets[0]['genders'] = genders
        facets[0]['start_date'] = sdates
        facets[0]['statuses'] = statuses
        del facets[0]['facet']

    return facets

@trial_router.post('/mlt', response_description="More Like This search for trials")
async def mlt_search(
    request: Request,
    trial: MLTModel = Body(...),
    limit: Optional[int] = 12,
    skip: Optional[int] = 0,
    use_vector: Optional[bool] = False):
    
    mlt_search = {
        '$search': {
            'index': 'default',
            'moreLikeThis': {
                'like': []
            },
        }
    }

    mlt_vector_search = {
        '$vectorSearch': {
            'index': 'trials_vector_index',
            'queryVector': [],
            'path': 'detailed_description_vector' if trial.description else 'brief_summary_vector',
            'numCandidates': 150,
            'limit': limit
        }
    }
  
    if trial.title and len(trial.title.strip()) > 0:
        if use_vector:
            mlt_vector_search['$vectorSearch']['queryVector'] = await get_cached_embeddings(request, trial.title)
        else:
            mlt_search['$search']['moreLikeThis']['like'].append({"brief_title": trial.title})

    if trial.description and len(trial.description.strip()) > 0:
        if use_vector:
            mlt_vector_search['$vectorSearch']['queryVector'] = await get_cached_embeddings(request, trial.description)
        else:
            mlt_search['$search']['moreLikeThis']['like'].append({"detailed_description": trial.description})
  
    add_fields = {
        '$addFields': {
            'score': {'$meta': 'searchScore'},
        }
    }

    if use_vector:
        add_fields['$addFields']['score'] = { '$meta': 'vectorSearchScore' }
  
    pipeline = [mlt_vector_search if use_vector else mlt_search, add_fields, mlt_trial_project]
    if not use_vector:
        pipeline.append({'$skip': skip})
        pipeline.append({'$limit': limit})

    #print(pipeline)
  
    trials = await request.app.mongodb["trials"].aggregate(pipeline).to_list()
    return trials[1:]
  
async def create_embeddings(text: str):
    model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
    return model.encode(text).tolist()

async def get_cached_embeddings(
    request: Request,
    text: str):

    # lookup the query cache
    lc_text = text.lower()
    cached_query = await request.app.mongodb["queries"].find_one({"query": lc_text})
    if cached_query and len(cached_query['vector']) > 0:
        vector = cached_query['vector']
        #print(f"Using cached vector: {vector[0:4]}")
    else:
        # embed the query
        vector = await create_embeddings(text)
        # cache the query vector
        if len(vector) > 0:
            inserted = await request.app.mongodb["queries"].insert_one({"query": lc_text, "vector": vector})
            #print(f"Caching query '{text}' - {inserted.inserted_id}")
        else:
            print("create_embedding returned an empty array?")

    return vector

async def create_openai_embeddings(text: str, client: OpenAI):
    response = client.embeddings.create(
        model= "text-embedding-ada-002",
        input=[text]
    )
    
    return response.data[0].embedding

async def filters_to_range_query(filters: List[str]):
    '''
    Converts an array of key:value filter expressions to a range 
     <https://www.mongodb.com/docs/atlas/atlas-search/range/> query
     or a vector search pre-filter expression
     <https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#atlas-vector-search-pre-filter>
    '''

    if (filters == None or len(filters) == 0):
        return None

    date_filters = [x for x in filters if x.startswith("start_date:") or x.startswith("effective_time:")]
    start_date = end_date = None
    if len(date_filters) > 0:
        parts = date_filters[0].split(":")
        p0 = parts[0] # field name
        p1 = parts[1] # ISO date value
        if p1 != None and p1.startswith("\""): # remove quotes
            p1 = p1[1:11]
        else:
            p1 = p1[0:10]
        start_date = datetime.strptime(p1, "%Y-%m-%d")
        end_date = start_date + timedelta(days=365)
    else:
        return None

    range_query = {}
    range_query['range'] = {
        'path': 'start_date' if p0 == 'start_date' else 'effective_time',
        'gte': start_date,
        'lt': end_date
    }
       
    print(f"range_query: {range_query}")
    return range_query

async def filters_to_mql_query(filters: List[str]):
    '''
    Converts an array of key:value filter expressions to an Atlas Vector Search
     MQL pre-filter expression 
     <https://www.mongodb.com/docs/atlas/atlas-vector-search/vector-search-stage/#atlas-vector-search-pre-filter/>
    '''
    if filters == None or len(filters) == 0:
        return None
    else:
        mql_query = {}
        for filter in filters:
            if filter.startswith("start_date:") or filter.startswith("effective_time:"):
                start_date = end_date = None
                parts = filter.split(":")
                p0 = parts[0] # field name
                p1 = parts[1] # ISO date value
                if p1 != None and p1.startswith("\""): # remove quotes
                    p1 = p1[1:11]
                else:
                    p1 = p1[0:10]
                start_date = datetime.strptime(p1, "%Y-%m-%d")
                end_date = start_date + timedelta(days=365)
                gte = { 'start_date' if p0 == 'start_date' else 'effective_time' : { '$gte': start_date } }
                lte = { 'start_date' if p0 == 'start_date' else 'effective_time' : { '$lte': end_date } }
                if '$and' in mql_query:
                    mql_query['$and'].append(gte)
                    mql_query['$and'].append(lte)
                else:
                    mql_query['$and'] = [gte, lte]

            else:
                parts = filter.split(":")
                field = parts[0]
                value = parts[1]
                if value and value.startswith("\""): # remove quotes
                    value = re.sub(r'["\']+', '', value)
                eq = { field: value }
                if '$and' in mql_query:
                    mql_query['$and'].append(eq)
                else:
                    mql_query['$and'] = [eq]

        print(f"mql_query: {mql_query}")
        return mql_query

async def filters_to_query_string(filters: List[str]):
    '''
    Converts an array of key:value filter expressions to an Atlas Search queryString
     <https://www.mongodb.com/docs/atlas/atlas-search/queryString/> operator
    '''

    if filters == None or len(filters) == 0:
        return None

    # skip date fields
    filters_no_dates = list(filter(lambda x: not x.startswith("start_date:"), filters))
    if len(filters_no_dates) == 0:
        return None
    elif len(filters_no_dates) == 1:
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
    use_vector: Optional[bool] = False,
    num_candidates: Optional[int] = 1000,
    pagination_token: Optional[str] = None,
    filters: Optional[List[str]] = Query(None)):
    
    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)
    mql_filter = await filters_to_mql_query(filters)

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
                'should': [{
                    'text': {
                        'query': term,
                        'path': [
                            'openfda.brand_name',
                        ],
                        'score': { 'boost': { 'value': 3 } }
                    }
                }],
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
            }
        }
    }
  
    search_with_filters = {
        '$search': {
            'index': 'drugs',
            'compound': {
                'should': [{
                    'text': {
                        'query': term,
                        'path': [
                            'openfda.brand_name',
                        ],
                        'score': { 'boost': { 'value': 3 } }
                    }
                }],
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
            }
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
        }
    }

    vector_search = {
        '$vectorSearch': {
            'index': 'drugs_vector_index', 
            'queryVector': [],
            'path': 'description_vector', 
            'numCandidates': num_candidates,
            'limit': limit
        }
    }
    if mql_filter != None:
        vector_search['$vectorSearch']['filter'] = mql_filter


    add_fields = {
        '$addFields': {
            'score': {'$meta': 'searchScore'},
            'highlights': {'$meta': 'searchHighlights'},
            'drug_pagination_token': {'$meta' : 'searchSequenceToken'},
        }
    }

    if (use_vector == True):
        if (term is None):
            raise HTTPException(status_code=422)
        else:
            add_fields['$addFields']['score'] = { '$meta': 'vectorSearchScore' }
            #drug_project['$project']['description'] = 1
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
            vector_search['$vectorSearch']['queryVector'] = await get_cached_embeddings(request, term)
            pipeline.append(vector_search)
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
        
    pipeline.extend([{'$limit': limit}, drug_project, add_fields])
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
    #print(pipeline)

    trials = await request.app.mongodb["drug_data"].aggregate(pipeline).to_list(length=limit)
    return trials

@drug_router.post("/facets", response_description="Facet search for drugs")
async def search_trial_facets(
    request: Request,
    term: Optional[str] = None,
    filters: Optional[List[str]] = Query(None),
    count_only: Optional[bool] = False):
    
    default_filter_field = filters[0].split(":")[0] if filters != None and len(filters) > 0 else ""
    query_string = await filters_to_query_string(filters)

    count_all_facets = {
        '$searchMeta': {
            'index': 'drugs',
            'exists': { 'path': 'id' },
            'count': { 'type': 'total' }
        }
    }

    count_facets_with_filters = {
        '$searchMeta': {
            'index': 'drugs',
            'compound': {
                'filter': [{
                    'queryString': {
                        'defaultPath': 'id',
                        'query': query_string
                    }
                }]
            },
            'count': { 'type': 'total' }
        }
    }
  
    drug_facets_object = {
        'manufacturers': {
            'type': 'string',
            'path': 'openfda.manufacturer_name',
            'numBuckets': 10
        },
        'routes': {
            'type': 'string',
            'path': 'openfda.route',
            'numBuckets': 10
        }
    }

    basic_facets_no_term = {
        '$searchMeta': {
            'index': 'drugs',
            'facet': {
                'facets': drug_facets_object
            }
        }
    }
  
    compound_operator = { 'compound': {} }
  
    if query_string and len(query_string) > 0:
        compound_operator['compound']['filter'] = [{
            'queryString': {
                'defaultPath': 'id',
                'query': query_string
            }
        }]

    if term and len(term.strip()) > 0:
        compound_operator['compound']['must'] = [{
            'text': {
                'query': term,
                'path': [
                    'openfda.brand_name', 'openfda.generic_name', 'openfda.manufacturer_name'
                ],
                'fuzzy': {
                    'maxEdits': 1,
                    'maxExpansions': 100
                }
            }
        }]
          
    search_facets_with_filters = {
        '$searchMeta': {
            'index': 'drugs',
            'facet': {
                'operator': compound_operator,
                'facets': drug_facets_object
            }   
        }
    }
  
    add_fields = { '$addFields': { 'count': '$$SEARCH_META.count' } }
    pipeline = []
  
    if count_only:
        print('count_only')
        if query_string and len(query_string.strip()) > 0:
            # filters provided
            pipeline.append(count_facets_with_filters)
        else:
            # no filters provided
            pipeline.append(count_all_facets)
    elif term and len(term.strip()) > 0:
        print(f"not count only, term: {term}")
        # search term provided
        pipeline.append(search_facets_with_filters)
    elif query_string and len(query_string.strip()) > 0:
        # filters provided
        pipeline.append(search_facets_with_filters)
    else:
        # no search term or filters provided
        pipeline.append(basic_facets_no_term)

    #pipeline.append(add_fields);
    #print(pipeline)
  
    facets = await request.app.mongodb["drug_data"].aggregate(pipeline).to_list()

    if not count_only:
        # reformat to match schema
        buckets = facets[0]['facet']['manufacturers']['buckets']
        manufacturers = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))
        buckets = facets[0]['facet']['routes']['buckets']
        routes = list(map(lambda bucket: {'name': bucket['_id'], 'count': bucket['count']}, buckets))
  
        facets[0]['manufacturers'] = manufacturers
        facets[0]['routes'] = routes
        del facets[0]['facet']
  
    return facets

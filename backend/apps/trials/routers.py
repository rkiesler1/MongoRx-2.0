from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException, Request, status, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from typing import Optional, List

from .models import TrialModel, DrugModel

from openai import OpenAI
from sentence_transformers import SentenceTransformer

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

@trial_router.get("/", response_description="List all trials")
async def list_trials(request: Request):
    trials = await request.app.mongodb["trials"].find(
        {}, trial_project['$project']).to_list(length=100)
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

@trial_router.post("/", response_description="Search for trials")
async def search_trials(
    request: Request,
    term: Optional[str] = None,
    limit: Optional[int] = 100,
    skip: Optional[int] = None,
    sort: Optional[str] = None,
    sort_order: Optional[int] = None,
    use_vector: Optional[bool] = False,
    num_candidates: Optional[int] = 100,
    pagination_token: Optional[str] = None,
    filters: Optional[List[str]] = Query(None)):
    basic_search_no_term = {
        '$search': {
            'index': 'default',
            'compound': {
                'filter': [{
                    'exists': {
                        'path': 'nct_id'
                    }
                }]
            },
            'count': {
                'type': 'total'
            }
        }
    }

    basic_search = {
        '$search': {
            'index': 'default',
            'compound': {
                'filter': [{
                    'exists': {
                        'path': 'nct_id'
                    }
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
                        'fuzzy': {
                            'maxEdits': 2,
                            'maxExpansions': 100
                        }
                    }
                }]
            },
            'count': {
                'type': 'total'
            },
            #'highlight': {
            #    'path': [
            #        'brief_summary',
            #        'detailed_description'
            #    ]
            #},
            'tracking': {
                'searchTerms': term
            }
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
        #searchNoTermWithFilters.$search.compound.filter.push(rangeQuery)
        #searchWithFilters.$search.compound.filter.push(rangeQuery)
        vector_search['$vectorSearch']['filter'] = range_query
    
    if (use_vector == True):
        add_fields['$addFields']['score'] = { '$meta': 'vectorSearchScore' }
    else:
        add_fields['$addFields']['count'] = '$$SEARCH_META.count'
    
    pipeline = []
    
    if (term is None):
        pipeline.append(basic_search_no_term)
    else:
        if (use_vector == True):
            vector_search['$vectorSearch']['queryVector'] = await create_embeddings(term) #create_openai_embeddings(term, client)
            pipeline.append(vector_search)
        else:
            pipeline.append(basic_search)
    
    pipeline.append(add_fields)
    pipeline.append(trial_project)
    #print(pipeline)

    trials = await request.app.mongodb["trials"].aggregate(pipeline).to_list(length=100)

    return trials

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
                '$gte': start_date#.strftime("%Y-%m-%d"),
            }
        }, {
            'start_date': {
                '$lte': end_date#.strftime("%Y-%m-%d")
            }
        }]
    else:
        range_query['range'] = {
            'path': 'start_date',
            'gte': start_date.strftime("%Y-%m-%d"),
            'lt': end_date.strftime("%Y-%m-%d")
        }
       
    return range_query

@drug_router.get("/", response_description="List all drugs")
async def list_drugs(request: Request):
    drugs = []
    for doc in await request.app.mongodb["drug_data"].find(
        {}, {'_id': 0}).to_list(length=100):
        drugs.append(doc)
    return drugs

@drug_router.get("/{uuid}", response_description="Get a single drug")
async def show_drug(uuid: str, request: Request):
    if (drug := await request.app.mongodb["drug_data"].find_one({"id": uuid}, {'_id': 0})) is not None:
        return drug

    raise HTTPException(status_code=404, detail=f"Drug {uuid} not found")

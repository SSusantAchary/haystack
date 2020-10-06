import os
from haystack import Document
from haystack.document_store.sql import SQLDocumentStore
from haystack.document_store.memory import InMemoryDocumentStore
from haystack.document_store.elasticsearch import Elasticsearch, ElasticsearchDocumentStore
from haystack.document_store.faiss import FAISSDocumentStore
from haystack.retriever.sparse import ElasticsearchRetriever, TfidfRetriever
from haystack.retriever.dense import DensePassageRetriever
from haystack.reader.farm import FARMReader
from haystack.reader.transformers import TransformersReader
from time import perf_counter
import pandas as pd
import json
import logging

from pathlib import Path
logger = logging.getLogger(__name__)


reader_models = ["deepset/roberta-base-squad2", "deepset/minilm-uncased-squad2", "deepset/bert-base-cased-squad2", "deepset/bert-large-uncased-whole-word-masking-squad2", "deepset/xlm-roberta-large-squad2"]
reader_types = ["farm"]
data_dir_reader = Path("../../data/squad20")
filename_reader = "dev-v2.0.json"

doc_index = "eval_document"
label_index = "label"

def get_document_store(document_store_type):
    """ TODO This method is taken from test/conftest.py but maybe should be within Haystack.
    Perhaps a class method of DocStore that just takes string for type of DocStore"""
    if document_store_type == "sql":
        if os.path.exists("haystack_test.db"):
            os.remove("haystack_test.db")
        document_store = SQLDocumentStore(url="sqlite:///haystack_test.db")
    elif document_store_type == "memory":
        document_store = InMemoryDocumentStore()
    elif document_store_type == "elasticsearch":
        # make sure we start from a fresh index
        client = Elasticsearch()
        client.indices.delete(index='haystack_test*', ignore=[404])
        document_store = ElasticsearchDocumentStore(index="eval_document")
    elif document_store_type in("faiss_flat", "faiss_hnsw"):
        import subprocess
        import time

        if document_store_type == "faiss":
            index_type = "Flat"
        elif document_store_type == "faiss_hnsw":
            index_type = "HNSW"
        try:
            document_store = FAISSDocumentStore(sql_url="postgresql://postgres:password@localhost:5432/haystack",
                                                faiss_index_factory_str=index_type)
        except:
            # Launch a postgres instance & create empty DB
            logger.info("Didn't find Postgres. Start a new instance...")
            status = subprocess.run(
                ['docker run --name haystack-postgres -p 5432:5432 -e POSTGRES_PASSWORD=password -d postgres'],
                shell=True)
            time.sleep(3)
            status = subprocess.run(
                ['docker exec -it haystack-postgres psql -U postgres -c "CREATE DATABASE haystack;"'], shell=True)
            document_store = FAISSDocumentStore(sql_url="postgresql://postgres:password@localhost:5432/haystack")

    else:
        raise Exception(f"No document store fixture for '{document_store_type}'")
    return document_store

def get_retriever(retriever_name, doc_store):
    if retriever_name == "elastic":
        return ElasticsearchRetriever(doc_store)
    if retriever_name == "tfidf":
        return TfidfRetriever(doc_store)
    if retriever_name == "dpr":
        return DensePassageRetriever(document_store=doc_store,
                                      query_embedding_model="facebook/dpr-question_encoder-single-nq-base",
                                      passage_embedding_model="facebook/dpr-ctx_encoder-single-nq-base",
                                      use_gpu=True)

def get_reader(reader_name, reader_type, max_seq_len=384):
    reader_class = None
    if reader_type == "farm":
        reader_class = FARMReader
    elif reader_type == "transformers":
        reader_class = TransformersReader
    return reader_class(reader_name, top_k_per_candidate=4, max_seq_len=max_seq_len)

def index_to_doc_store(doc_store, docs, retriever, labels=None):
    doc_store.delete_all_documents(index=doc_index)
    doc_store.delete_all_documents(index=label_index)
    doc_store.write_documents(docs, doc_index)
    if labels:
        doc_store.write_labels(labels, index=label_index)
    # these lines are not run if the docs.embedding field is already populated with precomputed embeddings
    # See the prepare_data() fn in the retriever benchmark script
    elif callable(getattr(retriever, "embed_passages", None)) and docs[0].embedding is None:
        doc_store.update_embeddings(retriever, index=doc_index)


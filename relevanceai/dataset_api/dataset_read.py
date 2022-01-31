"""
All read operations for Dataset
"""
import re
import math
import warnings
import pandas as pd
import numpy as np

from typing import Dict, List, Union

from relevanceai.dataset_api.helpers import _build_filters
from relevanceai.dataset_api.groupby import Groupby, Agg
from relevanceai.dataset_api.centroids import Centroids
from relevanceai.vector_tools.client import VectorTools
from relevanceai.api.client import BatchAPIClient


class Read(BatchAPIClient):
    """

    Dataset Read
    -------------------

    A Pandas Like datatset API for interacting with the RelevanceAI python package
    """

    def __init__(
        self,
        project: str,
        api_key: str,
        dataset_id: str,
        fields: list = [],
        image_fields: List[str] = [],
        audio_fields: List[str] = [],
        highlight_fields: List[str] = [],
        text_fields: List[str] = [],
    ):
        self.project = project
        self.api_key = api_key
        self.fields = fields
        self.dataset_id = dataset_id
        self.vector_tools = VectorTools(project=project, api_key=api_key)
        self.groupby = Groupby(self.project, self.api_key, self.dataset_id)
        self.agg = Agg(self.project, self.api_key, self.dataset_id)
        self.centroids = Centroids(self.project, self.api_key, self.dataset_id)
        self.image_fields = image_fields
        self.audio_fields = audio_fields
        self.highlight_fields = highlight_fields
        self.text_fields = text_fields
        super().__init__(project=project, api_key=api_key)

    @property
    def shape(self):
        """
        Returns the shape (N x C) of a dataset
        N = number of samples in the Dataset
        C = number of columns in the Dataset

        Returns
        -------
        Tuple
            (N, C)

        Example
        ---------------
        .. code-block::

            from relevanceai import Client

            client = Client()

            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)

            length, width = df.shape
        """
        schema = self.datasets.schema(self.dataset_id)
        n_documents = self.get_number_of_documents(dataset_id=self.dataset_id)
        return (n_documents, len(schema))

    def _get_possible_dtypes(self, schema):
        possible_dtypes = []
        for v in schema.values():
            if isinstance(v, str):
                possible_dtypes.append(v)
            elif isinstance(v, dict):
                if list(v)[0] == "vector":
                    possible_dtypes.append("vector_")
        return possible_dtypes

    def _get_dtype_count(self, schema: dict):
        possible_dtypes = self._get_possible_dtypes(schema)
        dtypes = {
            dtype: list(schema.values()).count(dtype) for dtype in possible_dtypes
        }
        return dtypes

    def _get_schema(self):
        # stores schema in memory to save users API usage/reloading
        if hasattr(self, "_schema"):
            return self._schema
        self._schema = self.datasets.schema(self.dataset_id)
        return self._schema

    def info(self, dtype_count: bool = False) -> pd.DataFrame:
        """
        Return a dictionary that contains information about the Dataset
        including the index dtype and columns and non-null values.

        Parameters
        -----------
        dtype_count: bool
            If dtype_count is True, prints a value_counts of the data type


        Returns
        ---------
        Dict
            Dictionary of information

        Example
        ---------------
        .. code-block::

            from relevanceai import Client

            client = Client()

            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            df.info()
        """
        health: dict = self.datasets.monitor.health(self.dataset_id)
        schema: dict = self._get_schema()
        info_json = [
            {
                "Column": column,
                "Dtype": schema[column],
            }
            if column not in health
            else {
                "Column": column,
                "Non-Null Count": health[column]["missing"],
                "Dtype": schema[column],
            }
            for column in schema
        ]

        info_df = pd.DataFrame(info_json)
        if dtype_count:
            dtypes_info = self._get_dtype_count(schema)
            print(dtypes_info)
        return info_df

    def head(
        self, n: int = 5, raw_json: bool = False, **kw
    ) -> Union[dict, pd.DataFrame]:
        """
        Return the first `n` rows.
        returns the first `n` rows of your dataset.
        It is useful for quickly testing if your object
        has the right type of data in it.

        Parameters
        ----------
        n : int, default 5
            Number of rows to select.
        raw_json: bool
            If True, returns raw JSON and not Pandas Dataframe
        kw:
            Additional arguments to feed into show_json

        Returns
        -------
        Pandas DataFrame or Dict, depending on args
            The first 'n' rows of the caller object.

        Example
        ---------
        .. code-block::

            from relevanceai import Client

            client = Client()

            df = client.Dataset("sample_dataset", image_fields=["image_url])

            df.head()
        """
        head_documents = self.get_documents(
            dataset_id=self.dataset_id,
            number_of_documents=n,
        )
        if raw_json:
            return head_documents
        else:
            try:
                return self._show_json(head_documents, **kw)
            except Exception as e:
                warnings.warn(
                    "Displaying using Pandas. To get image functionality please install RelevanceAI[notebook]. "
                    + str(e)
                )
                return pd.json_normalize(head_documents).head(n=n)

    def _show_json(self, documents, **kw):
        from jsonshower import show_json

        if not self.text_fields:
            text_fields = pd.json_normalize(documents).columns.tolist()
        else:
            text_fields = self.text_fields
        return show_json(
            documents,
            image_fields=self.image_fields,
            audio_fields=self.audio_fields,
            highlight_fields=self.highlight_fields,
            text_fields=text_fields,
            **kw,
        )

    def _repr_html_(self):
        documents = self.get_documents(dataset_id=self.dataset_id)
        try:
            return self._show_json(documents, return_html=True)
        except Exception as e:
            warnings.warn(
                "Displaying using pandas. To get image functionality please install RelevanceAI[notebook]. "
                + str(e)
            )
            return pd.json_normalize(documents).set_index("_id")._repr_html_()

    def sample(
        self,
        n: int = 1,
        frac: float = None,
        filters: list = [],
        random_state: int = 0,
        select_fields: list = [],
        include_vector: bool = True,
        output_format: str = "json",
    ):

        """
        Return a random sample of items from a dataset.

        Parameters
        ----------
        n : int
            Number of items to return. Cannot be used with frac.
        frac: float
            Fraction of items to return. Cannot be used with n.
        filters: list
            Query for filtering the search results
        random_state: int
            Random Seed for retrieving random documents.
        select_fields: list
            Fields to include in the search results, empty array/list means all fields.

        Example
        ---------

        .. code-block::

            from relevanceai import Client
            client = Client()
            df = client.Dataset("sample_dataset", image_fields=["image_url])
            df.sample()
        """
        if not select_fields and self.fields:
            select_fields = self.fields

        if frac and n:
            raise ValueError("Only one of n or frac can be provided")

        if frac:
            if frac > 1 or frac < 0:
                raise ValueError("Fraction must be between 0 and 1")
            n = math.ceil(
                self.get_number_of_documents(self.dataset_id, filters=filters) * frac
            )

        documents = self.datasets.documents.get_where(
            dataset_id=self.dataset_id,
            filters=filters,
            page_size=n,
            random_state=random_state,
            is_random=True,
            select_fields=select_fields,
            include_vector=include_vector,
        )["documents"]
        if output_format == "json":
            return documents
        elif output_format == "pandas":
            return pd.DataFrame.from_dict(documents, orient="records")

    def get_all_documents(
        self,
        chunksize: int = 1000,
        filters: List = [],
        sort: List = [],
        select_fields: List = [],
        include_vector: bool = True,
        show_progress_bar: bool = True,
    ):

        """
        Retrieve all documents with filters. Filter is used to retrieve documents that match the conditions set in a filter query. This is used in advance search to filter the documents that are searched. For more details see documents.get_where.

        Parameters
        ------------
        chunksize: list
            Number of documents to retrieve per retrieval
        include_vector: bool
            Include vectors in the search results
        sort: list
            Fields to sort by. For each field, sort by descending or ascending. If you are using descending by datetime, it will get the most recent ones.
        filters: list
            Query for filtering the search results
        select_fields : list
            Fields to include in the search results, empty array/list means all fields.

        Example
        ----------

        .. code-block::

            from relevanceai import Client
            client = Client()
            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            documents = df.get_all_documents()
        """

        return self._get_all_documents(
            dataset_id=self.dataset_id,
            chunksize=chunksize,
            filters=filters,
            sort=sort,
            select_fields=select_fields,
            include_vector=include_vector,
            show_progress_bar=show_progress_bar,
        )

    def get_documents_by_ids(
        self, document_ids: Union[List, str], include_vector: bool = True
    ):
        """
        Retrieve a document by its ID ("_id" field). This will retrieve the document faster than a filter applied on the "_id" field.

        Parameters
        ----------
        document_ids: Union[list, str]
            ID of a document in a dataset.
        include_vector: bool
            Include vectors in the search results

        Example
        --------

        .. code-block::

            from relevanceai import Client, Dataset
            client = Client()
            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            df.get_documents_by_ids(["sample_id"], include_vector=False)
        """
        if isinstance(document_ids, str):
            return self.datasets.documents.get(
                self.dataset_id, id=document_ids, include_vector=include_vector
            )
        elif isinstance(document_ids, list):
            return self.datasets.documents.bulk_get(
                self.dataset_id, ids=document_ids, include_vector=include_vector
            )
        raise TypeError("Document IDs needs to be a string or a list")

    def get(self, document_ids: Union[List, str], include_vector: bool = True):
        """
        Retrieve a document by its ID ("_id" field). This will retrieve the document faster than a filter applied on the "_id" field.
        This has the same functionality as get_document_by_ids.

        Parameters
        ----------
        document_ids: Union[list, str]
            ID of a document in a dataset.
        include_vector: bool
            Include vectors in the search results

        Example
        --------

        .. code-block::

            from relevanceai import Client
            client = Client()
            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            df.get(["sample_id"], include_vector=False)
        """
        if isinstance(document_ids, str):
            return self.datasets.documents.get(
                self.dataset_id, id=document_ids, include_vector=include_vector
            )
        elif isinstance(document_ids, list):
            return self.datasets.documents.bulk_get(
                self.dataset_id, ids=document_ids, include_vector=include_vector
            )
        raise TypeError("Document IDs needs to be a string or a list")

    @property
    def schema(self) -> Dict:
        """
        Returns the schema of a dataset. Refer to datasets.create for different field types available in a VecDB schema.

        Example
        -----------------

        .. code-block::

            from relevanceai import Client
            client = Client()
            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            df.schema
        """
        return self.datasets.schema(self.dataset_id)

    @property
    def columns(self) -> List[str]:
        """
        Returns a list of columns

        Example
        ----------

        .. code-block::

            from relevanceai import Client
            client = Client()
            dataset_id = "sample_dataset"
            df = client.Dataset(dataset_id)
            df.columns

        """
        return list(self.schema)

    def filter(
        self,
        index: Union[str, None] = None,
        items: Union[List, None] = None,
        like: Union[str, None] = None,
        regex: Union[str, None] = None,
        axis: Union[int, str] = 0,
    ):
        """
        Returns a subset of the dataset, filtered by the parameters given

        Parameters
        ----------
        items : str, default None
            the column on which to filter, if None then defaults to the _id column
        items : list-like
            Keep labels from axis which are in items.
        like : str
            Keep labels from axis for which "like in label == True".
        regex : str (regular expression)
            Keep labels from axis for which re.search(regex, label) == True.
        axis : {0 or `index`, 1 or `columns`},
            The axis on which to perform the search

        Returns
        ---------
        list of documents

        Example
        ----------

        .. code-block::

            from relevanceai import Client
            client = Client()
            df = client.Dataset("ecommerce-example-encoded")
            filtered = df.filter(items=["product_title", "query", "product_price"])
            filtered = df.filter(index="query", like="routers")
            filtered = df.filter(index="product_title", regex=".*Hard.*Drive.*")

        """
        fields = []
        filters = []

        schema = list(self.schema)

        if index:
            axis = 0
        else:
            axis = 1
            index = "_id"

        rows = axis in [0, "index"]
        columns = axis in [1, "columns"]

        if items is not None:
            if columns:
                fields += items

            elif rows:
                filters += _build_filters(items, filter_type="exact_match", index=index)

        elif like:
            if columns:
                fields += [column for column in schema if like in column]

            elif rows:
                filters += _build_filters(like, filter_type="contains", index=index)

        elif regex:
            if columns:
                query = re.compile(regex)
                re_fields = list(filter(query.match, schema))
                fields += re_fields

            elif rows:
                filters += _build_filters(regex, filter_type="regexp", index=index)

        else:
            raise TypeError("Must pass either `items`, `like` or `regex`")

        filters = [{"filter_type": "or", "condition_value": filters}]

        return self.get_all_documents(select_fields=fields, filters=filters)

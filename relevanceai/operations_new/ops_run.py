"""
Base class for base.py to inherit.
All functions related to running operations on datasets.
"""
from queue import Empty
import random
import psutil
import threading
import multiprocessing as mp
import warnings

from datetime import datetime
from typing import Any, Dict, List, Tuple, Union, Optional, Callable
from relevanceai.constants.constants import CONFIG

from relevanceai.dataset import Dataset
from relevanceai.operations_new.transform_base import TransformBase

from tqdm.auto import tqdm

from relevanceai.utils.helpers.helpers import getsizeof


class PullUpdatePush:

    pull_bar: tqdm
    update_bar: tqdm
    push_bar: tqdm

    pull_thread: threading.Thread
    update_threads: List[threading.Thread]
    push_threads: List[threading.Thread]

    def __init__(
        self,
        dataset: Dataset,
        func: Callable,
        func_args: Optional[Tuple[Any, ...]] = None,
        func_kwargs: Optional[Dict[str, Any]] = None,
        multithreaded_update: bool = True,
        pull_batch_size: Optional[int] = 128,
        update_batch_size: Optional[int] = 128,
        push_batch_size: Optional[int] = None,
        filters: Optional[list] = None,
        select_fields: Optional[list] = None,
        update_workers: int = 1,
        push_workers: int = 1,
        buffer_size: int = 0,
        show_progress_bar: bool = True,
        timeout: Optional[int] = None,
        ingest_in_background: bool = False,
        background_execution: bool = True,
        ram_ratio: float = 0.25,
        update_all_at_once: bool = False,
    ):
        """
        Buffer size:
            number of documents to be held in limbo by both queues at any one time

        """
        super().__init__()

        self.dataset = dataset
        self.dataset_id = dataset.dataset_id

        ndocs = self.dataset.get_number_of_documents(
            dataset_id=self.dataset_id,
            filters=filters,
        )
        self.ndocs = ndocs

        self.pull_batch_size = min(pull_batch_size, ndocs)
        self.update_batch_size = min(update_batch_size, ndocs)
        self.push_batch_size = push_batch_size

        self.update_all_at_once = update_all_at_once
        if update_all_at_once:
            self.update_batch_size = ndocs

        self.timeout = 30 if timeout is None else timeout
        self.ingest_in_background = ingest_in_background

        self.filters = [] if filters is None else filters
        self.select_fields = [] if select_fields is None else select_fields

        sample_documents = self.dataset.sample(
            n=10,
            filters=self.filters,
            select_fields=self.select_fields,
            random_state=hash(random.random()),
        )
        self.pull_batch_size = self._get_optimal_batch_size(sample_documents)

        self.general_lock = threading.Lock()
        self.update_batch_lock = threading.Lock()
        self.push_batch_lock = threading.Lock()
        self.func_lock: Union[threading.Lock, None]

        if not multithreaded_update:
            self.func_lock = threading.Lock()
            self.update_workers = 1
        else:
            self.func_lock = None
            self.update_workers = update_workers

        self.push_workers = push_workers

        self.func_args = () if func_args is None else func_args
        self.func_kwargs = {} if func_kwargs is None else func_kwargs

        if update_all_at_once:
            self.single_queue_size = ndocs

        else:
            if buffer_size == 0:
                ram_size = psutil.virtual_memory().total  # in bytes

                # assuming documents are 1MB, this is an upper limit and accounts for alot
                average_size = self._get_average_document_size(sample_documents)
                max_document_size = min(average_size, 2**20)

                total_queue_size = int(ram_size * ram_ratio / max_document_size)
            else:
                total_queue_size = buffer_size

            self.single_queue_size = int(total_queue_size / 2)

        tqdm.write(
            f"Setting max number of documents in queue to be: {self.single_queue_size:,}"
        )

        self.tq: mp.Queue = mp.Queue(maxsize=self.single_queue_size)
        self.pq: mp.Queue = mp.Queue(maxsize=self.single_queue_size)
        self.func = func

        self.tqdm_kwargs = dict(leave=True, disable=(not show_progress_bar))
        self.background_execution = background_execution

        self.config = CONFIG

    def _pull(self):
        """
        Iteratively pulls documents from a dataset and places them in the transform queue
        """
        documents: List[Dict[str, Any]] = [{"placeholder": "placeholder"}]
        after_id: Union[str, None] = None

        while documents:
            res = self.dataset.datasets.documents.get_where(
                dataset_id=self.dataset_id,
                page_size=self.pull_batch_size,
                filters=self.filters,
                select_fields=self.select_fields,
                sort=[],
                after_id=after_id,
            )
            documents = res["documents"]
            after_id = res["after_id"]

            for document in documents:
                self.tq.put(document)

            with self.general_lock:
                self.pull_bar.update(len(documents))

    def _get_average_document_size(self, sample_documents: List[Dict[str, Any]]):
        """
        Get average size of a document in memory.
        Returns size in bytes.
        """
        document_sizes = [
            getsizeof(sample_document) for sample_document in sample_documents
        ]
        return sum(document_sizes) / len(sample_documents)

    def _get_optimal_batch_size(self, sample_documents: List[Dict[str, Any]]) -> int:
        """
        Calculates the optimal batch size given a list of sampled documents and constraints in config
        """
        document_size = self._get_average_document_size(sample_documents)
        document_size = document_size / 2**20
        target_chunk_mb = int(self.config.get_option("upload.target_chunk_mb"))
        max_chunk_size = int(self.config.get_option("upload.max_chunk_size"))
        chunksize = int(target_chunk_mb / document_size)
        chunksize = min(chunksize, max_chunk_size)
        tqdm.write(f"Setting upload chunksize to {chunksize} documents")
        return chunksize

    def _get_update_batch(self) -> List[Dict[str, Any]]:
        """
        Collects a batches of of size `update_batch_size` from the transform queue
        """
        batch: List[Dict[str, Any]] = []

        queue = self.tq
        timeout = None
        batch_size = self.update_batch_size

        while self.update_all_at_once or not queue.empty():
            if len(batch) >= batch_size:
                break
            try:
                document = queue.get(timeout=timeout)
            except:
                break
            batch.append(document)

        return batch

    def _get_push_batch(self) -> List[Dict[str, Any]]:
        """
        Collects a batches of of size `push_batch_size` from the transform queue
        """
        batch: List[Dict[str, Any]] = []

        queue = self.pq
        timeout = 1

        # Calculate optimal batch size
        if self.push_batch_size is None:
            sample_documents = [queue.get(timeout=timeout) for _ in range(10)]
            self.push_batch_size = self._get_optimal_batch_size(sample_documents)
            batch = sample_documents

        batch_size = self.push_batch_size
        while len(batch) < batch_size:
            try:
                document = queue.get(timeout=timeout)
            except:
                break
            batch.append(document)

        return batch

    def _update(self):
        """
        Updates a batch of documents given an update function.
        After updating, remove all fields that are present in both old and new batches.
        ^ necessary to avoid reinserting stuff that is already in the cloud.
        Then, repeatedly put each document from the processed batch in the push queue
        """
        while self.update_bar.n < self.ndocs:
            with self.update_batch_lock:
                batch = self._get_update_batch()

            old_keys = [set(document.keys()) for document in batch]

            if self.func_lock is not None:
                with self.func_lock:
                    new_batch = self.func(batch, *self.func_args, **self.func_kwargs)
            else:
                new_batch = self.func(batch, **self.func_kwargs)

            batch = PullUpdatePush._postprocess(new_batch, old_keys)

            for document in batch:
                self.pq.put(document)

            with self.general_lock:
                self.update_bar.update(len(batch))

    def _handle_failed_documents(
        self,
        res: Dict[str, Any],
        batch: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Handles any documents that failed to upload.
        Does so by collecting by `_id` from the batch, and reinserting them in the push queue.
        """
        # check if there is any failed documents...
        failed_documents = res["response_json"]["failed_documents"]

        if failed_documents:
            with self.general_lock:
                self.ndocs += len(failed_documents)
                desc = f"push - failed_documents = {self.ndocs - self.ndocs}"
                self.push_bar.set_description(desc)

            # ...find these failed documents within the batch...
            failed_ids = set(map(lambda x: x["_id"], failed_documents))
            failed_documents = [
                document for document in batch if document["_id"] in failed_ids
            ]

            # ...and re add them to the push queue
            for failed_document in failed_documents:
                self.pq.put(failed_document)

        return failed_documents

    @staticmethod
    def _postprocess(
        new_batch: List[Dict[str, Any]],
        old_keys: List[str],
    ) -> List[Dict[str, Any]]:
        """
        Removes fields from `new_batch` that are present in the `old_keys` list.
        Necessary to avoid bloating the upload payload with unnecesary information.
        """
        batch = [
            {
                key: value
                for key, value in new_batch[idx].items()
                if key not in old_keys[idx] or key == "_id"
            }
            for idx in range(len(new_batch))
        ]
        return batch

    def _push(self) -> None:
        """
        Iteratively gather a batch of processed documents and push these to cloud
        """
        while self.push_bar.n < self.ndocs:
            with self.push_batch_lock:
                batch = self._get_push_batch()

            batch = self.dataset.json_encoder(batch)

            res = self.dataset.datasets.documents.bulk_update(
                self.dataset_id,
                batch,
                return_documents=True,
                ingest_in_background=self.ingest_in_background,
            )

            failed_documents = self._handle_failed_documents(res, batch)

            with self.general_lock:
                self.push_bar.update(len(batch) - len(failed_documents))

    def _init_progress_bars(self) -> None:
        """
        Initialise the progress bars for dispay progress on pulling updating and pushing.
        """
        self.pull_bar = tqdm(
            desc="pull",
            position=0,
            total=self.ndocs,
            **self.tqdm_kwargs,
        )
        self.update_bar = tqdm(
            range(self.ndocs),
            desc="update",
            position=1,
            **self.tqdm_kwargs,
        )
        self.push_bar = tqdm(
            range(self.ndocs),
            desc="push",
            position=2,
            **self.tqdm_kwargs,
        )

    def _init_worker_threads(self) -> None:
        """
        Initialise the worker threads for each process
        """
        self.pull_thread = threading.Thread(target=self._pull)
        self.update_threads = [
            threading.Thread(target=self._update) for _ in range(self.update_workers)
        ]
        self.push_threads = [
            threading.Thread(target=self._push) for _ in range(self.push_workers)
        ]

    def _run_worker_threads(self):
        """
        Start the worker threads and then join them in reversed order.
        """
        self.pull_thread.start()
        while True:
            if not self.tq.empty():
                for thread in self.update_threads:
                    thread.start()
                break
        while True:
            if not self.pq.empty():
                for thread in self.push_threads:
                    thread.start()
                break

        if self.background_execution:
            for thread in self.push_threads:
                thread.join()
            for thread in self.update_threads:
                thread.join()
            self.pull_thread.join()

    def run(self):
        """
        (Main Method)
        Do the pulling, the updating, and of course, the pushing.
        """
        if self.ndocs <= 0:
            return

        self._init_progress_bars()
        self._init_worker_threads()
        self._run_worker_threads()


class OperationRun(TransformBase):
    """
    All functions related to running transforms as an operation on datasets
    """

    def is_chunk_valid(self, chunk):
        return chunk is not None and len(chunk) > 0

    # @abstractmethod
    def post_run(self, dataset, documents, updated_documents):
        pass

    def run(
        self,
        dataset: Dataset,
        batched: Optional[bool] = False,
        chunksize: Optional[int] = 100,
        filters: Optional[list] = None,
        select_fields: Optional[list] = None,
        output_fields: Optional[list] = None,
        refresh: bool = False,
        *args,
        **kwargs,
    ):
        """It takes a dataset, and then it gets all the documents from that dataset. Then it transforms the
        documents and then it upserts the documents.

        Parameters
        ----------
        dataset : Dataset
            Dataset,
        select_fields : list
            Used to determine which fields to retrieve for filters
        output_fields: list
            Used to determine which output fields are missing to continue running operation

        filters : list
            list = None,

        """

        if filters is None:
            filters = []
        if select_fields is None:
            select_fields = []

        # store this
        if hasattr(dataset, "dataset_id"):
            self.dataset_id = dataset.dataset_id

        self._check_fields_in_schema(select_fields)

        filters += [
            {
                "filter_type": "or",
                "condition_value": [
                    {
                        "field": field,
                        "filter_type": "exists",
                        "condition": "==",
                        "condition_value": " ",
                    }
                    for field in select_fields
                ],
            }
        ]

        # add a checkmark for output fields
        if not refresh and output_fields is not None and len(output_fields) > 0:
            filters += [
                {
                    "field": output_fields[0],
                    "filter_type": "exists",
                    "condition": "!=",
                    "condition_value": " ",
                }
            ]

        # needs to be here due to circular imports
        from relevanceai.operations_new.ops_manager import OperationManager

        with OperationManager(
            dataset=dataset,
            operation=self,
        ) as dataset:
            self.batch_transform_upsert(
                dataset=dataset,
                select_fields=select_fields,
                filters=filters,
                chunksize=chunksize,
                update_all_at_once=(not batched),
                **kwargs,
            )
        return

    def batch_transform_upsert(
        self,
        dataset: Dataset,
        func_args: Optional[Tuple[Any]] = None,
        func_kwargs: Optional[Dict[str, Any]] = None,
        select_fields: list = None,
        filters: list = None,
        chunksize: int = None,
        update_workers: int = 2,
        push_workers: int = 2,
        timeout: int = 30,
        buffer_size: int = 0,
        show_progress_bar: bool = True,
        update_batch_size: int = 32,
        multithreaded_update: bool = False,
        update_all_at_once: bool = False,
        ingest_in_background: bool = True,
        **kwargs,
    ):
        if multithreaded_update:
            warnings.warn(
                "Multithreaded-update should be False for vectorizing with 1 GPU only. Could hang if True. Works fine on CPU."
            )
        pup = PullUpdatePush(
            dataset=dataset,
            func=self.transform,
            func_args=func_args,
            func_kwargs=func_kwargs,
            multithreaded_update=multithreaded_update,
            pull_batch_size=chunksize,
            update_batch_size=update_batch_size,
            push_batch_size=chunksize,
            filters=filters,
            select_fields=select_fields,
            update_workers=update_workers,
            push_workers=push_workers,
            buffer_size=buffer_size,
            show_progress_bar=show_progress_bar,
            timeout=timeout,
            update_all_at_once=update_all_at_once,
            ingest_in_background=ingest_in_background,
        )
        pup.run()

    def store_operation_metadata(
        self,
        dataset: Dataset,
        values: Optional[Dict[str, Any]] = None,
    ):
        """This function stores metadata about operators

        Parameters
        ----------
        dataset : Dataset
            Dataset,
        values : Optional[Dict[str, Any]]
            Optional[Dict[str, Any]] = None,

        Returns
        -------
            The dataset object with the metadata appended to it.

        .. code-block::

            {
                "_operationhistory_": {
                    "1-1-1-17-2-3": {
                        "operation": "vector",
                        "model_name": "miniLm"
                    },
                }
            }

        """
        if values is None:
            values = self.get_operation_metadata()

        tqdm.write("Storing operation metadata...")
        timestamp = str(datetime.now().timestamp()).replace(".", "-")
        metadata = dataset.metadata.to_dict()
        if "_operationhistory_" not in metadata:
            metadata["_operationhistory_"] = {}
        metadata["_operationhistory_"].update(
            {
                timestamp: {
                    "operation": self.name,
                    "parameters": str(values),
                }
            }
        )
        # Gets metadata and appends to the operation history
        return dataset.upsert_metadata(metadata)

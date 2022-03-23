import pytest

from sklearn.cluster import MiniBatchKMeans

from relevanceai.client import Client
from relevanceai.dataset import Dataset
from relevanceai.operations.cluster import ClusterOps

CLUSTER_ALIAS = "minibatch"
VECTOR_FIELDS = ["sample_1_vector_"]


@pytest.fixture(scope="function")
def test_batch_clusterer(test_client: Client, vector_dataset_id, test_df: Dataset):

    clusterer: ClusterOps = test_client.ClusterOps(
        alias=CLUSTER_ALIAS,
        model=MiniBatchKMeans(),
        dataset_id=vector_dataset_id,
        vector_fields=VECTOR_FIELDS,
    )

    clusterer.vector_fields = VECTOR_FIELDS
    closest = clusterer.list_closest_to_center(
        dataset=vector_dataset_id, vector_fields=VECTOR_FIELDS
    )
    assert len(closest["results"]) > 0

    clusterer.vector_fields = VECTOR_FIELDS
    furthest = clusterer.list_furthest_from_center(
        dataset=vector_dataset_id,
        vector_fields=VECTOR_FIELDS,
    )
    assert len(furthest["results"]) > 0

    df = test_client.Dataset(vector_dataset_id)
    clusterer.partial_fit_predict_update(
        dataset=df,
        vector_fields=VECTOR_FIELDS,
    )

    assert f"_cluster_.{VECTOR_FIELDS[0]}.{CLUSTER_ALIAS}" in df.schema

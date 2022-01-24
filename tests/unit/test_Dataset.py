import pytest


class TestDatset:
    def test_Dataset(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        assert True

    def test_info(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        info = df.info()
        assert True

    def test_shape(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        shape = df.shape
        assert True

    def test_head(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        head = df.head()
        assert True

    def test_describe(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        description = df.describe()
        assert True

    def test_cluster(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        centroids = df.cluster(field="sample_1_vector_", overwrite=True)
        assert True

    def test_groupby_agg(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        agg = df.agg({"sample_1_label": "avg"})
        groupby_agg = df.groupby(["sample_1_description"]).agg(
            {"sample_1_label": "avg"}
        )
        assert True

    def test_groupby_mean_method(self, test_client, test_dataset_df):
        manual_mean = test_dataset_df.groupby(["sample_1_label"]).agg(
            {"sample_1_value": "avg"}
        )

        assert manual_mean == test_dataset_df.groupby(["sample_1_label"]).mean(
            "sample_1_value"
        )

    def test_centroids(self, test_client, test_clustered_dataset):
        df = test_client.Dataset(test_clustered_dataset)
        closest = df.centroids(["sample_1_vector_"], "kmeans_10").closest()
        furthest = df.centroids(["sample_1_vector_"], "kmeans_10").furthest()
        agg = df.centroids(["sample_1_vector_"], "kmeans_10").agg(
            {"sample_2_label": "avg"}
        )
        groupby_agg = (
            df.centroids(["sample_1_vector_"], "kmeans_10")
            .groupby(["sample_3_description"])
            .agg({"sample_2_label": "avg"})
        )
        assert True

    def test_sample(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        sample_n = df.sample(n=10)
        assert len(sample_n) == 10

    def test_series_sample(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        sample_n = df["sample_1_label"].sample(n=10)
        assert len(sample_n) == 10

    def test_series_sample(self, test_client, test_sample_vector_dataset):
        df = test_client.Dataset(test_sample_vector_dataset)
        sample_n = df[["sample_1_label", "sample_2_label"]].sample(n=10)
        assert len(sample_n) == 10
        assert len(sample_n[0].keys()) == 3
"""
This script demonstrates a function based approach for clustering with KMeans Using the new Pandas-Like Dataset API for RelevanceAI Python Package
"""

import argparse

from relevanceai import Client


def main(args):
    client = Client()

    df = client.Dataset(args.dataset_id)
    vector_field = args.vector_field
    n_clusters = args.n_clusters

    centroids = df.cluster(vector_field, n_clusters, overwrite=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="faiss_clustering")

    parser.add_argument("dataset_id", help="The dataset_id of the dataset to cluster")
    parser.add_argument("vector_field", help="The vector field over which to cluster")
    parser.add_argument("n_clusters", help="The number of clusters to find")

    args = parser.parse_args()
    main(args)

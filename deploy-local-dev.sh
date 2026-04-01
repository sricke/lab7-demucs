#!/bin/sh
#
# You can use this script to launch Redis and minio on Kubernetes
# and forward their connections to your local computer. That means
# you can then work on your worker-server.py and rest-server.py
# on your local computer rather than pushing to Kubernetes with each change.
#
# To kill the port-forward processes us e.g. "ps augxww | grep port-forward"
# to identify the processes ids
#

apply_if_exists () {
  if [ -f "$1" ]; then
    kubectl apply -f "$1"
  else
    echo "Skipping missing manifest: $1"
  fi
}

apply_if_exists "redis/redis-deployment.yaml"
apply_if_exists "redis/redis-service.yaml"
apply_if_exists "rest/rest-deployment.yaml"
apply_if_exists "rest/rest-service.yaml"
apply_if_exists "logs/logs-deployment.yaml"
apply_if_exists "worker/worker-deployment.yaml"
apply_if_exists "minio/minio-external-service.yaml"

kubectl port-forward --address 0.0.0.0 service/redis 6379:6379 &

# Forward MinIO S3 API and Console ports.
kubectl port-forward -n minio-ns --address 0.0.0.0 service/minio-proj 9000:9000 &
kubectl port-forward -n minio-ns --address 0.0.0.0 service/minio-proj-console 9001:9090 &
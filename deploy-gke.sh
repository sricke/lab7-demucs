#!/bin/sh
# Create a GKE cluster, push images to Artifact Registry, apply manifests, point
# Deployments at the registry images.
#
# Override when calling, e.g.:
#   GCP_ZONE=us-central1-b CREATE_CLUSTER=0 ./deploy-gke.sh
#
# If CREATE_CLUSTER=1 and the cluster already exists, creation is skipped and
# the script still builds, pushes, and applies (redeploy).
#
# Requires: gcloud auth, docker, kubectl; PROJECT_ID from gcloud config or env.
set -e

# GKE nodes are linux/amd64. Building mac leads to arm64 images
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
export DOCKER_BUILDKIT=1

GCP_ZONE="${GCP_ZONE:-us-central1-a}"
CLUSTER_NAME="${CLUSTER_NAME:-demucs-cluster}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-8}"
REPO="${REPO:-demucs-registry}"
CREATE_CLUSTER="${CREATE_CLUSTER:-1}"

PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
  echo "Set gcloud project (gcloud config set project ID) or export PROJECT_ID." >&2
  exit 1
fi

# Artifact Registry is regional; derive from zone
REGION="${REGION:-$(gcloud compute zones describe "$GCP_ZONE" --format='value(region)' | awk -F/ '{print $NF}')}"

echo "Using project=$PROJECT_ID zone=$GCP_ZONE region=$REGION cluster=$CLUSTER_NAME docker_platform=$DOCKER_PLATFORM"

# check if the cluster exists
if [ "$CREATE_CLUSTER" = "1" ]; then
  if gcloud container clusters describe "$CLUSTER_NAME" --zone "$GCP_ZONE" >/dev/null 2>&1; then
    echo "Cluster $CLUSTER_NAME already exists in $GCP_ZONE; skipping create, continuing deploy."
  else
    gcloud container clusters create "$CLUSTER_NAME" \
      --zone "$GCP_ZONE" \
      --num-nodes 1 \
      --machine-type "$MACHINE_TYPE" \
      --enable-ip-alias
  fi
else
  echo "Skipping cluster create (CREATE_CLUSTER=0)."
fi

# add credentials to kubectl so map to the cluster
gcloud container clusters get-credentials "$CLUSTER_NAME" --zone "$GCP_ZONE"
echo "kubectl context set for $CLUSTER_NAME in $GCP_ZONE"

# Registry location must be a region, not a zone.
if ! gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION"
else
  echo "Artifact Registry repository $REPO already exists in $REGION."
fi

# configure the docker client to use the registry
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

REST_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/demucs-rest:latest"
WORKER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/demucs-worker:latest"

docker build --platform "$DOCKER_PLATFORM" -f Dockerfile-rest -t "$REST_IMAGE" .
docker push "$REST_IMAGE"

docker build --platform "$DOCKER_PLATFORM" -f worker/Dockerfile -t "$WORKER_IMAGE" worker
docker push "$WORKER_IMAGE"

# apply the manifests
kubectl apply -f redis/redis-deployment.yaml
kubectl apply -f redis/redis-service.yaml
kubectl apply -f logs/logs-deployment.yaml
kubectl apply -f rest/rest-backendconfig.yaml
kubectl apply -f rest/rest-deployment.yaml
kubectl apply -f rest/rest-service.yaml
kubectl apply -f rest/rest-ingress-gce.yaml
kubectl apply -f worker/worker-deployment.yaml
kubectl apply -f minio/minio-namespace.yaml
kubectl apply -f minio/minio-deployment.yaml
kubectl apply -f minio/minio-service.yaml
kubectl apply -f minio/minio-external-service.yaml
kubectl rollout status deployment/minio-proj -n minio-ns --timeout=180s

kubectl set image deployment/rest rest="$REST_IMAGE"
kubectl set image deployment/worker worker="$WORKER_IMAGE"

echo "Rollout status:"
kubectl rollout status deployment/rest --timeout=900s
kubectl rollout status deployment/worker --timeout=900s
kubectl get pods

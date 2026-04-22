# MLOps Starter

This repository contains a small FastAPI-based model serving example with supporting infrastructure for Docker, Kubernetes, Terraform, and GitHub Actions.

The application currently exposes a simple health endpoint and a placeholder prediction endpoint. The prediction logic is intentionally minimal, so the repo can be used as a starting point for a fuller MLOps workflow.

## What is included

- FastAPI app in [app/app.py](app/app.py)
- Python dependencies in [app/requirements.txt](app/requirements.txt)
- Docker image definition in [Dockerfile](Dockerfile)
- Kubernetes manifests in [k8s/deployment.yaml](k8s/deployment.yaml) and [k8s/service.yaml](k8s/service.yaml)
- Terraform infrastructure for a Google Kubernetes Engine cluster in [terraform/main.tf](terraform/main.tf)
- GitHub Actions workflow in [.github/workflows/deploy.yml](.github/workflows/deploy.yml)

## Prerequisites

- Python 3.9 or newer
- pip
- Docker
- kubectl
- Terraform
- A Google Cloud project if you plan to use the Terraform and Kubernetes resources as written

## Run locally

1. Create and activate a virtual environment.
2. Install the dependencies.
3. Start the app.

```bash
cd app
pip install -r requirements.txt
python app.py
```

The API will be available on port `8080`.

### Example requests

Health check:

```bash
curl http://localhost:8080/
```

Prediction endpoint:

```bash
curl -X POST http://localhost:8080/predict \
	-H "Content-Type: application/json" \
	-d '{"feature_1": 1, "feature_2": 2}'
```

## Docker

Build the image from the repository root:

```bash
docker build -t ml-model:latest .
```

Run the container:

```bash
docker run -p 8080:8080 ml-model:latest
```

If you keep the application source inside the app/ directory, make sure the container command points to the FastAPI entry file there.

## Kubernetes

The Kubernetes manifests deploy the model service behind a `LoadBalancer` service.

Apply them after your image is available in a registry that your cluster can pull from:

```bash
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

## Terraform

The Terraform configuration provisions a Google Kubernetes Engine cluster.

Typical workflow:

```bash
cd terraform
terraform init
terraform plan -var="project_id=YOUR_PROJECT_ID"
terraform apply -var="project_id=YOUR_PROJECT_ID"
```

## CI/CD

The GitHub Actions workflow in [.github/workflows/deploy.yml](.github/workflows/deploy.yml) currently builds and pushes a container image, then applies the Kubernetes deployment.

Before using it in a real environment, update the placeholder registry values, add authentication, and make sure the deployment step points to the correct manifests and cluster context.

## Notes

- The prediction endpoint currently returns a dummy response.
- The repository is structured so you can replace the placeholder inference logic with a trained model and wire it into the deployment pipeline.

# site/k8s/

This project's Kubernetes patches, one folder per environment that runs on Kubernetes
(`site/k8s/<env>/kustomization.yaml`, a Component), applied last: replicas, resources, the
ingress class, a storage class. Settings never go here: they go in `site/config/`, which both
targets read. Empty until Kubernetes is built (docs/plan.md, phase E).

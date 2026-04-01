VERSION=v1
DOCKERUSER=YOUR_DOCKER_USERNAME_HERE

build:
	docker build --platform linux/amd64 -f Dockerfile -t demucs-worker .
push:
	docker tag demucs-worker $(DOCKERUSER)/demucs-worker:$(VERSION)
	docker push $(DOCKERUSER)/demucs-worker:$(VERSION)
	docker tag demucs-worker $(DOCKERUSER)/demucs-worker:latest
	docker push $(DOCKERUSER)/demucs-worker:latest

FROM xserrat/facebook-demucs:latest

RUN pip3 install --upgrade minio redis requests

COPY worker-server.py /worker-server.py
COPY requirements.txt /requirements.txt

# Base image sets ENTRYPOINT to bash -c; without clearing it, CMD is not run as intended.
ENTRYPOINT []
CMD ["python3", "/worker-server.py"]
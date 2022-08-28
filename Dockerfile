FROM python:3

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py ./
COPY .environ.example ./
COPY README.md ./
CMD [ "python", "./server.py"  ]

FROM python:3.10

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

COPY . .

CMD ["gunicorn", "-b", "0.0.0.0:4200", "-k","aiohttp.worker.GunicornWebWorker", "main:app","--reload"]

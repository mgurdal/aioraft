FROM python:3.7
ENV PYTHONUNBUFFERED 1

RUN mkdir /aioraft
WORKDIR /aioraft

COPY requirements.txt /aioraft/requirements.txt
RUN pip install -r requirements.txt

COPY . /aioraft/

EXPOSE 50051
CMD ["python", "main.py"]

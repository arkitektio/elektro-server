FROM python:3.10

# Install dependencies
RUN pip install poetry rich
RUN poetry config virtualenvs.create false 
ENV PYTHONUNBUFFERED=1

# Debug mounts
RUN mkdir /workspaces


# Copy dependencies
COPY pyproject.toml /
COPY poetry.lock /
RUN poetry install --no-root


# Install App
RUN mkdir /workspace
ADD . /workspace
WORKDIR /workspace

CMD ["bash", "run.sh"]




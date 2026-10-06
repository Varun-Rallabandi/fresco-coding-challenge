PY ?= .venv/bin/python

setup:            ## create the virtualenv and install everything
	python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

data:             ## download the challenge specbooks into data/
	.venv/bin/pip install gdown && .venv/bin/gdown --folder https://drive.google.com/drive/folders/1jKHE6iAjHukarkkfzvBNbjhiSNeLkTr3 -O data

extract-all:      ## run every specbook in data/ -> outputs/
	$(PY) -m hwsets.cli batch data -o outputs

eval:             ## score against the hand-checked answer keys
	$(PY) -m eval.score

test:             ## unit tests (no PDFs needed)
	$(PY) -m pytest -q

ui:               ## review screen at http://localhost:8501
	.venv/bin/streamlit run app/streamlit_app.py

api:              ## HTTP API with background jobs at http://localhost:8000/docs
	.venv/bin/uvicorn api.server:app --reload

.PHONY: setup data extract-all eval test ui api

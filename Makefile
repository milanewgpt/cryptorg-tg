.PHONY: install run seed access

install:
	pip install -r requirements.txt

run:
	python main.py

access:
	python get_access_list.py

seed:
	python seed_templates.py

.PHONY: format check

format:
	npx --yes prettier@3.9.6 --write README.md
	shfmt -i 2 -w packages/*/PKGBUILD .github/scripts/*.sh
	uvx ruff@0.16.9 format .github/scripts/*.py

check:
	npx --yes prettier@3.9.6 --check README.md
	shfmt -i 2 -d packages/*/PKGBUILD .github/scripts/*.sh
	uvx ruff@0.16.9 format --check .github/scripts/*.py
	uvx ruff@0.16.9 check .github/scripts/*.py
	uvx mypy@2.3.1 .github/scripts/*.py
	python3 -m py_compile .github/scripts/*.py

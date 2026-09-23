.PHONY: format check

format:
	npx --yes prettier@3.9.6 --write README.md web/index.html web/404.html web/styles.css web/app.js
	shfmt -i 2 -w packages/*/PKGBUILD

check:
	npx --yes prettier@3.9.6 --check README.md web/index.html web/404.html web/styles.css web/app.js
	python3 -m py_compile .github/scripts/set_matrix.py .github/scripts/pkgdb.py
	shfmt -i 2 -d packages/*/PKGBUILD

.PHONY: format

format:
	npx --yes prettier@3.9.6 --write README.md web/index.html web/styles.css web/app.js
	shfmt -i 2 -w packages/*/PKGBUILD
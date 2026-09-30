.PHONY: format check

format:
	npx --yes prettier@3.9.6 --write README.md
	shfmt -i 2 -w packages/*/PKGBUILD

check:
	npx --yes prettier@3.9.6 --check README.md
	shfmt -i 2 -d packages/*/PKGBUILD

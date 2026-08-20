.PHONY: format

format:
	prettier --write README.md
	shfmt -i 2 -w packages/*/PKGBUILD
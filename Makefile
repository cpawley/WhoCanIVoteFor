export DJANGO_SETTINGS_MODULE?=wcivf.settings.lambda
export DC_ENVIRONMENT?=development
export AWS_DEFAULT_REGION?=eu-west-2

.PHONY: all
make all: build clean

.PHONY: build
build:
	sam build -t ./sam-template.yaml

.PHONY: clean
clean: ## Delete any unneeded static asset files and git-restore the rendered API documentation file
	rm -rf .aws-sam/build/WCIVFControllerFunction/wcivf/static/booklets/
	rm -rf .aws-sam/build/WCIVFControllerFunction/wcivf/assets/booklets/
	rm -rf .aws-sam/build/WCIVFControllerFunction/wcivf/media/
	rm -f .aws-sam/build/WCIVFControllerFunction/wcivf/settings/local.py

.PHONY: lambda-migrate
lambda-migrate:  ## Invoke lambda to migrate the database
	aws lambda invoke \
	--function-name WCIVFControllerFunction \
	--payload '{ "command": "migrate" }' \
	/dev/stdout

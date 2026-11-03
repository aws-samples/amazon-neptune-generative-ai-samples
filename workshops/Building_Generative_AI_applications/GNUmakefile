# Build and deploy the "Building Generative AI applications using knowledge graphs in
# Amazon Neptune" workshop from this repository.
#
#   make deploy          create the assets bucket, upload the assets and deploy the stack
#   make outputs         show the notebook and application URLs
#   make delete          delete the stack (asks for confirmation)
#
# Settings can be overridden on the command line, for example:
#   make deploy AWS_REGION=us-west-2 STACK_NAME=my-workshop
#
# Works with GNU Make 3.81 (the version included with macOS) and later.

SHELL := /bin/bash

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
# AWS CLI profile; empty uses the default credential chain
AWS_PROFILE ?=
# Region for the stack and the assets bucket; defaults to the profile's region
AWS_REGION ?= $(shell aws configure get region $(if $(AWS_PROFILE),--profile $(AWS_PROFILE)) 2>/dev/null)
# CloudFormation stack name. The notebook instance is named aws-neptune-<STACK_NAME>.
STACK_NAME ?= genai-workshop
# Bedrock model or inference profile used by the sample application
LLM_MODEL ?= us.anthropic.claude-sonnet-5-5
NOTEBOOK_INSTANCE_TYPE ?= ml.t3.medium

AWS := aws $(if $(AWS_PROFILE),--profile $(AWS_PROFILE)) --region $(AWS_REGION)

# Looked up once, and only by targets that need it
ACCOUNT_ID = $(eval ACCOUNT_ID := $(shell $(AWS) sts get-caller-identity --query Account --output text))$(ACCOUNT_ID)

# Assets bucket in your account, in the stack's Region. Neptune Analytics loads data
# only from buckets in the graph's Region.
BUCKET ?= neptune-genai-workshop-$(ACCOUNT_ID)-$(AWS_REGION)
# Key prefix for this stack's assets, so several stacks can share a bucket
PREFIX ?= $(STACK_NAME)/

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
TEMPLATE := cloudformation/workshop.yaml
APP_DIR := ../../solutions/sbom-pgi-chatbot
BUILD := build
STAGE := $(BUILD)/stage

# Files that are never uploaded
EXCLUDES := --exclude .DS_Store --exclude __pycache__ --exclude '*.pyc' \
	--exclude .ipynb_checkpoints --exclude .env --exclude venv --exclude .venv

.DEFAULT_GOAL := help
.PHONY: help check lint package bucket upload deploy outputs delete delete-assets delete-bucket clean

help: ## Show this help
	@echo "Usage: make <target> [AWS_PROFILE=...] [AWS_REGION=...] [STACK_NAME=...] [LLM_MODEL=...]"
	@echo
	@grep -E '^[a-z-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'
	@echo
	@echo "Current settings: AWS_REGION=$(AWS_REGION) STACK_NAME=$(STACK_NAME) PREFIX=$(PREFIX)"
	@echo "                  LLM_MODEL=$(LLM_MODEL)"

check: ## Check the AWS CLI, credentials and Region
	@command -v aws >/dev/null || { echo "The AWS CLI is required: https://aws.amazon.com/cli/"; exit 1; }
	@test -n "$(AWS_REGION)" || { echo "Set AWS_REGION, or configure a default Region for your profile"; exit 1; }
	@test -n "$(ACCOUNT_ID)" || { echo "No AWS credentials found for profile '$(or $(AWS_PROFILE),default)'"; exit 1; }
	@echo "Account $(ACCOUNT_ID), Region $(AWS_REGION), stack $(STACK_NAME), assets s3://$(BUCKET)/$(PREFIX)"

lint: ## Lint the CloudFormation template with cfn-lint
	@if cfn-lint --version >/dev/null 2>&1; then cfn-lint $(TEMPLATE); \
	elif command -v uvx >/dev/null; then uvx cfn-lint $(TEMPLATE); \
	else echo "Install cfn-lint (pip install cfn-lint) or uv to lint the template"; exit 1; fi
	@echo "$(TEMPLATE): no cfn-lint findings"

package: ## Build the assets to upload into build/stage
	rm -rf $(STAGE)
	mkdir -p $(STAGE)/persist
	rsync -a $(EXCLUDES) notebooks/ $(STAGE)/notebooks/
	rsync -a assets/ $(STAGE)/
	# Notebook 4 copies the saved PropertyGraphIndex from persist/
	cp notebooks/app/persist/pgi/*.json $(STAGE)/persist/
	# The finished application, run by the notebook instance on port 8080
	COPYFILE_DISABLE=1 tar --format=ustar -czf $(STAGE)/sbom-pgi-chatbot.tar.gz \
		$(EXCLUDES) --exclude tests -C $(dir $(APP_DIR)) $(notdir $(APP_DIR))
	@echo "Staged $$(find $(STAGE) -type f | wc -l | tr -d ' ') files in $(STAGE)"

bucket: check ## Create the assets bucket if it doesn't exist
	@if $(AWS) s3api head-bucket --bucket $(BUCKET) 2>/dev/null; then \
		region=$$($(AWS) s3api get-bucket-location --bucket $(BUCKET) --query LocationConstraint --output text); \
		case "$$region" in None|null|"") region=us-east-1;; esac; \
		if [ "$$region" != "$(AWS_REGION)" ]; then \
			echo "s3://$(BUCKET) is in $$region, but the stack is in $(AWS_REGION). Set BUCKET to a bucket in $(AWS_REGION)."; exit 1; \
		fi; \
		echo "Using existing bucket s3://$(BUCKET)"; \
	else \
		echo "Creating bucket s3://$(BUCKET)"; \
		if [ "$(AWS_REGION)" = "us-east-1" ]; then \
			$(AWS) s3api create-bucket --bucket $(BUCKET) >/dev/null; \
		else \
			$(AWS) s3api create-bucket --bucket $(BUCKET) \
				--create-bucket-configuration LocationConstraint=$(AWS_REGION) >/dev/null; \
		fi; \
		$(AWS) s3api put-public-access-block --bucket $(BUCKET) --public-access-block-configuration \
			BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true; \
	fi

upload: package bucket ## Upload the staged assets to the bucket
	$(AWS) s3 sync $(STAGE)/ s3://$(BUCKET)/$(PREFIX) --delete --only-show-errors
	@echo "Uploaded assets to s3://$(BUCKET)/$(PREFIX)"

deploy: upload ## Upload the assets and create or update the stack
	$(AWS) cloudformation deploy \
		--template-file $(TEMPLATE) \
		--stack-name $(STACK_NAME) \
		--capabilities CAPABILITY_IAM \
		--no-fail-on-empty-changeset \
		--parameter-overrides \
			AssetsBucketName=$(BUCKET) \
			AssetsBucketPrefix=$(PREFIX) \
			NotebookName=$(STACK_NAME) \
			NotebookInstanceType=$(NOTEBOOK_INSTANCE_TYPE) \
			LlmModelId=$(LLM_MODEL) \
		--tags project=neptune-genai-workshop
	@$(MAKE) --no-print-directory outputs
	@echo
	@echo "The notebook instance copies the notebooks on its first start. To give an existing"
	@echo "instance updated notebooks, delete the stack and deploy again."

outputs: ## Show the stack outputs (notebook and application URLs)
	@$(AWS) cloudformation describe-stacks --stack-name $(STACK_NAME) \
		--query 'Stacks[0].Outputs[].[OutputKey,OutputValue]' --output table

delete: ## Delete the stack, including both graphs and the notebook instance
	@if [ "$(CONFIRM)" != "yes" ]; then \
		read -r -p "Delete stack $(STACK_NAME) in $(AWS_REGION), including its graphs and notebook instance? [y/N] " answer; \
		case "$$answer" in [yY]|[yY][eE][sS]) ;; *) echo "Cancelled"; exit 1;; esac; \
	fi
	$(AWS) cloudformation delete-stack --stack-name $(STACK_NAME)
	$(AWS) cloudformation wait stack-delete-complete --stack-name $(STACK_NAME)
	@echo "Deleted stack $(STACK_NAME). The assets are still in s3://$(BUCKET)/$(PREFIX); run 'make delete-assets' to remove them."

delete-assets: check ## Delete this stack's assets from the bucket
	@if [ "$(CONFIRM)" != "yes" ]; then \
		read -r -p "Delete everything under s3://$(BUCKET)/$(PREFIX)? [y/N] " answer; \
		case "$$answer" in [yY]|[yY][eE][sS]) ;; *) echo "Cancelled"; exit 1;; esac; \
	fi
	$(AWS) s3 rm s3://$(BUCKET)/$(PREFIX) --recursive --only-show-errors
	@echo "Deleted s3://$(BUCKET)/$(PREFIX). The bucket is kept; run 'make delete-bucket' to remove it when it's empty."

delete-bucket: check ## Delete the assets bucket (only succeeds when it's empty)
	$(AWS) s3api delete-bucket --bucket $(BUCKET)
	@echo "Deleted bucket s3://$(BUCKET)"

clean: ## Remove the local build directory
	rm -rf $(BUILD)

# Rykkeforløb på borgere med ukendt adresse

This is an RPA built for use with [OpenOrchestrator](https://github.com/itk-dev-rpa/OpenOrchestrator).
This process will notify citizens without an address that they are required to register an address with the city.
The robot will use the Nova API to allow caseworkers to manage activities and monitor case status.
Using Serviceplatformen, this robot will send both NemSMS to notify and Digital Post to citizens.

## Quick start
Assign a Nova RPA caseworker ID to this robot.
Provide credentials for the Nova API in your Open Orchestrator instance.
Provide the credentials and URLs for a hvac vault in your Open Orchestrator instance.
Set up the RPA process in Open Orchestrator and watch the robot run.

## Requirements
python version 3.11
OpenOrchestrator version 2.*
itk-dev-shared-components version 2.*
hvac version 2.*
itk_dev_event_log version 1.*

## Linting and Github Actions

This template is also setup with flake8 and pylint linting in Github Actions.
This workflow will trigger whenever you push your code to Github.
The workflow is defined under `.github/workflows/Linting.yml`.


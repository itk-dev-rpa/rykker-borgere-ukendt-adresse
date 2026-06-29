# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.1.0 - 26/06/2026

- Mark undelivered reminder letters ("Ikke sendt") and advance the reminder step when the citizen is not registered for Digital Post
- Send a NemSMS notification (Danish and English) after a delivered letter when the citizen is NemSMS-subscribed
- Retry the registration-status check on transient Service Platform errors
- Send an aggregated backoffice email per run for citizens with no case or a high reminder step
- Skip cases marked "Oplyst"
- Record Nova notes in the dry-run report so it matches production

## 1.0.1 - 25/06/2026

- Fixed notes being added before anything was sent out
- Fixed error handling on missing notes

## 1.0.0 - 24/06/2026

- Initial release

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## 1.1.3 - 07/07/2026

- Ignore reminder notes ("Rykker X sendt") dated before go-live (config.REMINDER_NOTE_CUTOFF) so undeletable test notes from live testing don't make the robot skip real reminders
- People younger than 18 are skipped


## 1.1.2 - 31/06/2026

- Fixed upload filename derived from the file's real .pdf basename
- Changed caseworker type to user
- Added batch limit {"limit": N} via OO process arguments
- Hardened the upload_document call with keyword args, and made operational logs English

## 1.1.1 - 30/06/2026

- Added init to project
- Added file-relative paths to folders

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

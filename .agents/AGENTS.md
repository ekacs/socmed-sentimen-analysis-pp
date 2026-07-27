# Project Rules: socmed-sentimen-analysis-pp

## Git & Repository Rules
- **Automatic Git Fetch**: Always execute `git fetch --all` before inspecting project status, reviewing commits, or evaluating remote changes from contributors.
- **Remote Synchronization**: Check whether local branches are up to date with `origin` before conducting codebase analysis.

## Workflow & Code Standards
- **Data & Scraper Pipeline**: Preserve existing architectural patterns in `01_run_scraper.py`, `01_pipeline_data.py`, `config_parser.py`, and `app.py`.
- **Environment Safety**: Never hardcode, expose, or overwrite sensitive secrets or credentials stored in `.env`.

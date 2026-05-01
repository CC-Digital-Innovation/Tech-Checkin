# Tech Checkin
## Summary
The Tech checkin schedules texts to be sent 24 hours prior to an appointment to confirm appointment details are correct in source sheet, schedules texts to be sent 1 hour prior to appoiintment and updates the source sheet with confirmations/corrections. the 24 hour text is a link to a form that autofills with details from the source sheet and gives the tech a chance to make any corrections.

## Platforms
* n8n: Hosts the form and sends the results back to the code
* Kubernetes: Hosts the api and job scheduling and n8n
* Concourse/Argo: CI/CD

## Code Flow
```mermaid
flowchart TD
    A[API/CronJob start] -->|CronJob| B(Todays 1 hr texts)
    B --> |1 hours prior| H(Text reminder)
    A[API/CronJob start] -->|CronJob| C(Todays 24 hr texts)
    C --> |24 hours prior| I(Text link to form)
    I --> |On form submit| G
    H -->  J("Update Smartsheet")
    A[API/CronJob start] --> D(API Endpoints)
    D --> |GET| E(Jobs)
    D --> |POST| F(Creat Jobs)
    D --> |POST| G(submit form)
    G--> J
```

## Code Requirements
* apscheduler: Schedules Jobs
* fastapi: API Framework
* geopy: get Timezones
* loguru: Logging
* phonenumbers: Phone Number formatting
* pydantic: Class and Data Modeling
* python-dotenv: env reader
* pytz: handle timezones
* requests
* smartsheet-python-sdk
* uvicorn: serve fast api
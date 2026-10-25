# Deploying FaultTrace

For whoever runs this for a workshop network, a fleet operator or an OEM service team.

## Running it

```bash
docker build -t faulttrace .
docker run -d --name faulttrace -p 8000:8000 \
  -v faulttrace-data:/data -e FAULTTRACE_API_KEY="$(openssl rand -hex 24)" faulttrace
```

The image runs as an unprivileged user, has a health check (`/health`), and keeps the database in `/data`.
It was built and exercised in testing: the container reached the healthy state, answered a diagnosis,
and the stored diagnosis survived a restart. Without Docker: `pip install -r requirements.txt` then
`uvicorn faulttrace.api:create_app --factory --host 0.0.0.0 --port 8000`.

| Variable | Meaning |
|---|---|
| `FAULTTRACE_API_KEY` | If set, every endpoint except `/health` requires it in `X-API-Key`. Set it |
| `FAULTTRACE_DB` | SQLite file for diagnoses and feedback (default `faulttrace.db`, `/data/faulttrace.db` in the image) |

Vehicle configs are loaded once per process. After editing a YAML file, restart the service.

## Security

- **Use the API key**, and put the service behind TLS (a reverse proxy or the platform's ingress). The key is
  sent in a header and the service itself does not terminate TLS.
- The key check is a single shared secret. It is enough for an internal service and not a substitute for
  per-user authentication; if you need to know which technician did what, put an identity-aware proxy in
  front, or extend the `technician` field of the feedback call.
- Vehicle names are never used as file paths, inputs are length-limited (500 events, 2,000 J1939 frames,
  32-character codes), and the VIN is validated.
- **VINs can identify a person.** In many jurisdictions a VIN linked to an owner or a repair history counts
  as personal data. Decide with your data-protection contact whether to store them. The VIN is optional;
  omit it and nothing in the store identifies a vehicle.

## Data retention and deletion

Nothing is deleted automatically. Two tools are provided:

```bash
python -m faulttrace purge --older-than-days 365        # retention: delete diagnoses (and feedback) older than a year
curl -X DELETE localhost:8000/history/<VIN> -H "X-API-Key: ..."    # erasure: everything for one vehicle
```

Run the first from cron, or from a scheduled container job that mounts the same volume.

## Backups

The store is one SQLite file. Take a consistent copy with SQLite's backup API, which is safe while the
service is writing (plain file copies are not):

```bash
python -c "import sqlite3; src = sqlite3.connect('/data/faulttrace.db'); src.backup(sqlite3.connect('/backup/faulttrace.db'))"
```

This runs inside the container, or on any host with Python that can see the volume.

## Scaling

SQLite allows one writer at a time, which is far more than diagnosis traffic needs: a warm diagnosis took
about 12 ms in testing, mostly spent in the simulation cache that is built on the first request per
vehicle (about 130 ms). One instance covers a busy workshop network. If you need several instances behind a
load balancer, replace `faulttrace/store.py` with a client-server database; the rest of the code only
talks to the seven public methods of that class. This has not been done or tested.

## Monitoring

- `GET /health` for liveness. It checks that the service answers, not that diagnoses are good.
- `GET /stats` for the number that matters: field accuracy per verdict from technician feedback. Alert when
  `by_verdict.verified.correct` drops well below the lab value (92% on synthetic data), which means the
  vehicle model no longer matches reality.
- Each diagnosis stores `version` and `config_sha`. After a model change you can compare accuracy before and
  after, because every result says which config produced it.

## Rolling it out

The lab numbers come from synthetic incidents and say nothing yet about your vehicles. A sensible path:

1. **Build the model.** Take the component graph from the wiring or system diagrams, the signal-to-component
   mapping from the OEM's diagnostic documentation, and repair actions and times from the service manual.
   Edge probabilities start at a default and are refined later ([ADDING_A_VEHICLE.md](ADDING_A_VEHICLE.md)).
2. **Shadow mode.** Run diagnoses next to the existing process and show them to nobody. Record the repair
   that turned out to be the real fix through `POST /diagnoses/{id}/feedback`.
3. **Read `/stats`.** Is a "verified" verdict as reliable as the lab says? Is the true cause in the
   inspection plan? Fix the model where it is wrong (edge probabilities, missing links, silent parts).
4. **Assisted mode.** Show the report to technicians as a second opinion, still recording the outcome.
5. **Tune with data.** With a few hundred confirmed cases, estimate failure rates (the `failure_rate`
   priors) and edge probabilities from the history. Estimating them automatically is on the roadmap.

## What this is not

It is decision support for a technician. It does not replace measurement, it has not been validated for any
safety-related decision, and a `verified` verdict means the simulated fault reproduces the observed codes
under the configured model, not that the part has been tested.

from railway_sdk import define_railway, github, postgres, preserve, project, service, volume


@define_railway
def main(_ctx=None):
    Postgres = postgres("Postgres", region="sfo")
    postgres_volume = volume(
        "postgres-volume",
        {
            "alerts": {"usage": {"100": {}, "80": {}, "95": {}}},
            "allowOnlineResize": True,
            "region": "sfo",
            "sizeMB": 500,
        },
    )
    rekha = service(
        "rekha",
        source=github("IndAlok/rekha", checkSuites=False),
        healthcheck="/health",
        healthcheckTimeout=180,
        replicas={"sfo": 1},
        env={
            "DATABASE_URL": Postgres.env.DATABASE_URL,
            "REKHA_ENV": "prod",
            "CORS_ORIGINS": "https://rekha-one.vercel.app",
            "AUTO_EVAL_ON_BOOT": "true",
            "PAYMENTS_ADAPTER": "sandbox",
            "RAILWAY_DOCKERFILE_PATH": "infra/Dockerfile.api",
            "RAILWAY_HEALTHCHECK_TIMEOUT_SEC": "180",
            "OPS_TOKEN": preserve(),
            "RAZORPAY_WEBHOOK_SECRET": preserve(),
        },
    )
    return project("protective-learning", resources=[rekha, Postgres, postgres_volume])

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class LazyMainASGI:
    def __init__(self, app: ASGIApp):
        self.app = app
        self.main_app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["path"] in {"/", "/health"}:
            await self.app(scope, receive, send)
            return

        try:
            if self.main_app is None:
                import main
                self.main_app = main.app

            await self.main_app(scope, receive, send)
        except Exception as exc:
            response = JSONResponse(
                status_code=500,
                content={"error": "Failed to load application", "detail": str(exc)},
            )
            await response(scope, receive, send)


app = FastAPI(
    title="Claims Processing Pipeline",
    description="Minimal Vercel app entrypoint for the claims pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_origins=[
        "https://medical-claim-processor-frontend.vercel.app",
        "https://medical-claim-processor-frontend-paez-dfzrok4ik.vercel.app",
        "https://medical-claim-processor-frontend-pa.vercel.app",
        "http://localhost:3000",
        "http://localhost:4173",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Claims Processing Pipeline",
        "message": "FastAPI app is running.",
    }


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Claims Processing Pipeline", "version": "1.0.0"}


@app.get("/debug/startup")
async def debug_startup():
    try:
        import main  # noqa: F401
        return {
            "status": "ok",
            "message": "Main application imported successfully.",
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Main application import failed.",
                "detail": str(exc),
            },
        )


app = LazyMainASGI(app)

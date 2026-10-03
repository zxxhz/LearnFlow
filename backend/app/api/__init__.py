from fastapi import APIRouter

from app.api import (
    annotations,
    bank,
    conversations,
    courses,
    dashboard,
    documents,
    execution,
    exercise,
    feynman,
    imports,
    math,
    quiz,
    review,
    runtime,
    search,
    settings,
    study,
    system,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(imports.router)  # /courses/import 需先于 /courses/{id} 注册
api_router.include_router(settings.router)
api_router.include_router(courses.router)
api_router.include_router(documents.router)
api_router.include_router(annotations.router)
api_router.include_router(conversations.router)
api_router.include_router(feynman.router)
api_router.include_router(review.router)
api_router.include_router(dashboard.router)
api_router.include_router(execution.router)
api_router.include_router(exercise.router)
api_router.include_router(quiz.router)
api_router.include_router(bank.router)
api_router.include_router(math.router)
api_router.include_router(runtime.router)
api_router.include_router(study.router)
api_router.include_router(search.router)
api_router.include_router(system.router)

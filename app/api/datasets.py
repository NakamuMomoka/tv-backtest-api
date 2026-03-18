from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.dataset import DatasetDetail, DatasetListItem
from app.services import dataset_service


router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post(
    "",
    response_model=DatasetDetail,
    summary="Create dataset from CSV file",
)
async def create_dataset_endpoint(
    name: str = Form(...),
    symbol: str | None = Form(default=None),
    timeframe: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> DatasetDetail:
    dataset = dataset_service.create_dataset(
        db,
        name=name,
        symbol=symbol,
        timeframe=timeframe,
        upload_file=file,
    )
    return DatasetDetail.model_validate(dataset)


@router.get(
    "",
    response_model=list[DatasetListItem],
    summary="List datasets",
)
async def list_datasets_endpoint(
    db: Session = Depends(get_db),
) -> list[DatasetListItem]:
    datasets = dataset_service.list_datasets(db)
    return [DatasetListItem.model_validate(ds) for ds in datasets]


@router.get(
    "/{dataset_id}",
    response_model=DatasetDetail,
    summary="Get dataset by id",
)
async def get_dataset_endpoint(
    dataset_id: int,
    db: Session = Depends(get_db),
) -> DatasetDetail:
    dataset = dataset_service.get_dataset(db, dataset_id=dataset_id)
    return DatasetDetail.model_validate(dataset)


@router.delete(
    "/{dataset_id}",
    summary="Delete dataset by id",
)
async def delete_dataset_endpoint(
    dataset_id: int,
    db: Session = Depends(get_db),
) -> dict:
    return dataset_service.delete_dataset(db, dataset_id=dataset_id)


@router.post(
    "/builtins/sync",
    summary="Sync builtin datasets from manifest",
)
async def sync_builtin_datasets_endpoint(
    db: Session = Depends(get_db),
) -> dict:
    result = dataset_service.sync_builtin_datasets(db)
    return {
        "created_count": len(result.get("created", [])),
        "updated_count": len(result.get("updated", [])),
        "skipped_count": len(result.get("skipped", [])),
        "created": result.get("created", []),
        "updated": result.get("updated", []),
        "skipped": result.get("skipped", []),
        "error": result.get("error"),
    }


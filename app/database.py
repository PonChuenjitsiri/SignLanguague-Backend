from motor.motor_asyncio import AsyncIOMotorClient
from app.config import get_settings

settings = get_settings()


class Database:
    client: AsyncIOMotorClient = None
    db = None


db_instance = Database()


async def connect_db():
    """Connect to MongoDB on application startup."""
    db_instance.client = AsyncIOMotorClient(settings.MONGODB_URL)
    db_instance.db = db_instance.client[settings.DATABASE_NAME]
    print(f"✅ Connected to MongoDB: {settings.DATABASE_NAME}")


async def close_db():
    """Close MongoDB connection on application shutdown."""
    if db_instance.client:
        db_instance.client.close()
        print("❌ MongoDB connection closed")


def get_database():
    """Get the database instance."""
    return db_instance.db

from sqlalchemy import create_engine, Column, String, Float, Integer, DateTime, Enum as PgEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine.base import Engine
from sqlalchemy.orm.session import Session
from sqlalchemy.sql import func
from typing import Optional
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from uuid import uuid4
import os

# Base class for SQLAlchemy models
Base = declarative_base()

class OHLCV(Base):
    """
    SQLAlchemy model representing the `ohlcv_1d` table in the `futures_data` schema.
    
    Attributes:
        time (datetime): The timestamp for the data entry (primary key).
        symbol (str): The symbol or identifier for the instrument (primary key).
        open (float): The opening price for the interval.
        high (float): The highest price for the interval.
        low (float): The lowest price for the interval.
        close (float): The closing price for the interval.
        volume (int): The trading volume for the interval.
    """
    __tablename__ = "ohlcv_1d"
    __table_args__ = {"schema": "futures_data"}

    time: Column = Column(DateTime, primary_key=True, nullable=False)
    symbol: Column = Column(String, primary_key=True, nullable=False)
    open: Column = Column(Float, nullable=False)
    high: Column = Column(Float, nullable=False)
    low: Column = Column(Float, nullable=False)
    close: Column = Column(Float, nullable=False)
    volume: Column = Column(Integer, nullable=False)

class ContractMetadata(Base):
    __tablename__ = "contract_metadata"
    __table_args__ = {"schema": "metadata"}

    databento_symbol = Column("Databento Symbol", String, primary_key=True, nullable=False)
    ib_symbol = Column("IB Symbol", String, nullable=False)
    name = Column("Name", String, nullable=False)
    exchange = Column("Exchange", String, nullable=False)
    intraday_initial_margin = Column("Intraday Initial Margin", String, nullable=False)
    intraday_maintenance_margin = Column("Intraday Maintenance Margin", String, nullable=False)
    overnight_initial_margin = Column("Overnight Initial Margin", String, nullable=False)
    overnight_maintenance_margin = Column("Overnight Maintenance Margin", String, nullable=False)
    asset_type = Column("Asset Type", String, nullable=False)
    sector = Column("Sector", String, nullable=False)
    contract_size = Column("Contract Size", String, nullable=False)
    units = Column("Units", String, nullable=False)
    minimum_price_fluctuation = Column("Minimum Price Fluctuation", String, nullable=False)
    tick_size = Column("Tick Size", String, nullable=False)
    settlement_type = Column("Settlement Type", String, nullable=False)
    trading_hours = Column("Trading Hours (EST)", String, nullable=False)
    data_provider = Column("Data Provider", String, nullable=False)
    dataset = Column("Dataset", String, nullable=False)
    newest_month_additions = Column("Newest Month Additions", String, nullable=False)
    contract_months = Column("Contract Months", String, nullable=False)
    time_of_expiry = Column("Time of Expiry", String, nullable=False)

def get_engine() -> Engine:
    """
    Create and configure a SQLAlchemy Engine to connect to the TimescaleDB database.
    Database credentials are loaded from a `.env` file.

    Environment Variables:
        - DB_USER (str): The username for database authentication.
        - DB_PASSWORD (str): The password for database authentication.
        - DB_HOST (str): The database server hostname or IP.
        - DB_PORT (str): The port number for database access.
        - DB_NAME (str): The name of the database.

    Returns:
        Engine: A SQLAlchemy Engine object for database interactions.

    Raises:
        ValueError: If any required environment variable is missing.
    """
    # Load environment variables from .env file
    load_dotenv()

    # Retrieve database connection parameters from environment variables
    db_user: Optional[str] = os.getenv("DB_USER")
    db_password: Optional[str] = os.getenv("DB_PASSWORD")
    db_host: Optional[str] = os.getenv("DB_HOST")
    db_port: Optional[str] = os.getenv("DB_PORT")
    db_name: Optional[str] = os.getenv("DB_NAME")

    # Validate that all required parameters are present
    if not all([db_user, db_password, db_host, db_port, db_name]):
        raise ValueError(
            "One or more required environment variables are missing. "
            "Ensure DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, and DB_NAME are set in the .env file."
        )

    # Build the connection string
    connection_string: str = (
        f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
    )

    # Create and return the SQLAlchemy Engine
    return create_engine(connection_string)


def get_session(engine: Engine) -> Session:
    """
    Create a new SQLAlchemy session for database interactions.

    Args:
        engine (Engine): A SQLAlchemy Engine object connected to the database.

    Returns:
        Session: A SQLAlchemy Session object for executing database queries.
    """
    SessionFactory = sessionmaker(bind=engine)
    return SessionFactory()

class User(Base):
    """
    SQLAlchemy model representing users for authentication and account management.

    Attributes:
        id (int): Primary key, unique user identifier.
        email (str): User's email address (unique).
        password_hash (str): Hashed password for authentication.
        created_at (datetime): Timestamp of account creation.
        role (string): Role Based Access Control (public, general member, team lead, exec board)
    """
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id = Column(Integer, primary_key=True, default = str(uuid4()))
    email = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    role = Column(
        PgEnum(
            'general_member',
            'team_lead',
            'exec_board',
            name = 'user_role',
            create_type = False
        ),
        nullable=False,
        default='general_member'
    )

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f"<User {self.email}({self.role})"
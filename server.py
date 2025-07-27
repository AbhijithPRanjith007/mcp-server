import asyncio
import json
import logging  # Added logging
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from urllib.parse import quote

import mcp.server.stdio  # For running as a stdio server
from dotenv import load_dotenv

# ADK Tool Imports
from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.mcp_tool.conversion_utils import adk_to_mcp_tool_type

# MCP Server Imports
from mcp import types as mcp_types  # Use alias to avoid conflict
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

load_dotenv()

# --- Logging Setup ---
LOG_FILE_PATH = os.path.join(os.path.dirname(__file__), "mcp_server_activity.log")
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, mode="w"),
    ],
)
# --- End Logging Setup ---

# Database credentials
username = "abhijithpranjith"
password = "Abhi@8281"
host = "34.46.74.12"
port = "5432"
database = "student"

# URL encode the password to handle special characters
password = quote(password)

# Construct the database URI
DATABASE_URI = f"postgresql://{username}:{password}@{host}:{port}/{database}"

# Create the SQLAlchemy engine
engine = create_engine(DATABASE_URI, echo=True)

# Create a declarative base class for your ORM models
Base = declarative_base()

# Create a session factory bound to the engine
session_factory = sessionmaker(bind=engine)

# Create a scoped session to handle thread-local sessions
scoped_session_factory = scoped_session(session_factory)

# Optionally, specify the default schema here if you want all tables to use it
metadata = MetaData(schema="app")

# --- JSON Serialization Helper ---
def json_serializer(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

# --- Database Utility Functions ---


def get_db_connection():
    """Get a connection to Google Cloud SQL PostgreSQL database using SQLAlchemy."""
    try:
        connection = engine.connect()
        return connection
    except Exception as e:
        logging.error(f"Error connecting to Google Cloud SQL PostgreSQL: {e}")
        raise


def list_db_tables(dummy_param: str) -> dict:
    """Lists all tables in the PostgreSQL database.

    Args:
        dummy_param (str): This parameter is not used by the function
                           but helps ensure schema generation. A non-empty string is expected.
    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'tables' (list[str]) containing the table names if successful.
    """
    try:
        conn = get_db_connection()
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'app';"
        ))
        tables = [row[0] for row in result.fetchall()]
        conn.close()
        return {
            "success": True,
            "message": "Tables listed successfully.",
            "tables": tables,
        }
    except Exception as e:
        return {"success": False, "message": f"Error listing tables: {e}", "tables": []}


def get_table_schema(table_name: str) -> dict:
    """Gets the schema (column names and types) of a specific table."""
    conn = get_db_connection()
    try:
        result = conn.execute(text("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = :table_name AND table_schema = 'app'
            ORDER BY ordinal_position;
        """), {"table_name": table_name})
        schema_info = result.fetchall()
        
        if not schema_info:
            raise ValueError(f"Table '{table_name}' not found or no schema information.")

        columns = [{"name": row[0], "type": row[1]} for row in schema_info]
        return {"table_name": table_name, "columns": columns}
    finally:
        conn.close()


def query_db_table(table_name: str, columns: str, condition: str) -> list[dict]:
    """Queries a table with an optional condition.

    Args:
        table_name: The name of the table to query.
        columns: Comma-separated list of columns to retrieve (e.g., "id, name"). Defaults to "*".
        condition: Optional SQL WHERE clause condition (e.g., "id = 1" or "completed = 0").
    Returns:
        A list of dictionaries, where each dictionary represents a row.
    """
    conn = get_db_connection()
    try:
        query = f"SELECT {columns} FROM app.{table_name}"
        if condition:
            query += f" WHERE {condition}"
        
        result = conn.execute(text(query))
        # Convert result to list of dictionaries
        columns_list = result.keys()
        results = [dict(zip(columns_list, row)) for row in result.fetchall()]
        return results
    except Exception as e:
        raise ValueError(f"Error querying table '{table_name}': {e}")
    finally:
        conn.close()


def insert_data(table_name: str, data: dict) -> dict:
    """Inserts a new row of data into the specified table.

    Args:
        table_name (str): The name of the table to insert data into.
        data (dict): A dictionary where keys are column names and values are the
                     corresponding values for the new row.

    Returns:
        dict: A dictionary with keys 'success' (bool) and 'message' (str).
              If successful, 'message' includes the ID of the newly inserted row.
    """
    if not data:
        return {"success": False, "message": "No data provided for insertion."}

    conn = get_db_connection()
    try:
        columns = ", ".join(data.keys())
        placeholders = ", ".join([f":{key}" for key in data.keys()])
        
        query = f"INSERT INTO app.{table_name} ({columns}) VALUES ({placeholders}) RETURNING id"
        
        result = conn.execute(text(query), data)
        last_row_id = result.fetchone()[0] if result.rowcount > 0 else None
        conn.commit()
        
        return {
            "success": True,
            "message": f"Data inserted successfully. Row ID: {last_row_id}",
            "row_id": last_row_id,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error inserting data into table '{table_name}': {e}",
        }
    finally:
        conn.close()


def delete_data(table_name: str, condition: str) -> dict:
    """Deletes rows from a table based on a given SQL WHERE clause condition.

    Args:
        table_name (str): The name of the table to delete data from.
        condition (str): The SQL WHERE clause condition to specify which rows to delete.
                         This condition MUST NOT be empty to prevent accidental mass deletion.

    Returns:
        dict: A dictionary with keys 'success' (bool) and 'message' (str).
              If successful, 'message' includes the count of deleted rows.
    """
    if not condition or not condition.strip():
        return {
            "success": False,
            "message": "Deletion condition cannot be empty. This is a safety measure to prevent accidental deletion of all rows.",
        }

    conn = get_db_connection()
    try:
        query = f"DELETE FROM app.{table_name} WHERE {condition}"
        result = conn.execute(text(query))
        rows_deleted = result.rowcount
        conn.commit()
        
        return {
            "success": True,
            "message": f"{rows_deleted} row(s) deleted successfully from table '{table_name}'.",
            "rows_deleted": rows_deleted,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error deleting data from table '{table_name}': {e}",
        }
    finally:
        conn.close()


def get_academic_records(student_id: Optional[int] = None, subject: Optional[str] = None, teacher_id: Optional[int] = None) -> dict:
    """Gets academic records with optional filtering by student_id, subject, or teacher_id.

    Args:
        student_id (int, optional): Filter by student ID.
        subject (str, optional): Filter by subject name.
        teacher_id (int, optional): Filter by teacher ID.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'records' (list[dict]) containing the academic records if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT ar.id, ar.student_id, s.student_name, ar.subject, ar.grade, 
                   ar.record_date, ar.teacher_id, u.name as teacher_name,
                   ar.created_at, ar.updated_at
            FROM app.academic_records ar
            LEFT JOIN app.students s ON ar.student_id = s.student_id
            LEFT JOIN app.users u ON ar.teacher_id = u.id
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("ar.student_id = :student_id")
            params["student_id"] = student_id
        
        if subject is not None:
            conditions.append("ar.subject ILIKE :subject")
            params["subject"] = f"%{subject}%"
        
        if teacher_id is not None:
            conditions.append("ar.teacher_id = :teacher_id")
            params["teacher_id"] = teacher_id
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY ar.record_date DESC"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        records = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(records)} academic records.",
            "records": records,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving academic records: {e}",
            "records": [],
        }
    finally:
        conn.close()


def add_academic_record(student_id: int, subject: str, grade: str, record_date: str, teacher_id: Optional[int] = None) -> dict:
    """Adds a new academic record for a student.

    Args:
        student_id (int): The ID of the student.
        subject (str): The subject name.
        grade (str): The grade received (e.g., 'A', 'B+', '85').
        record_date (str): The date of the record (YYYY-MM-DD format).
        teacher_id (int, optional): The ID of the teacher who assigned the grade.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'record_id' (int) if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            INSERT INTO app.academic_records (student_id, subject, grade, record_date, teacher_id)
            VALUES (:student_id, :subject, :grade, :record_date, :teacher_id)
            RETURNING id
        """
        
        params = {
            "student_id": student_id,
            "subject": subject,
            "grade": grade,
            "record_date": record_date,
            "teacher_id": teacher_id
        }
        
        result = conn.execute(text(query), params)
        record_id = result.fetchone()[0]
        conn.commit()
        
        return {
            "success": True,
            "message": f"Academic record added successfully for student {student_id}.",
            "record_id": record_id,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error adding academic record: {e}",
        }
    finally:
        conn.close()


def get_attendance_records(
    student_id: Optional[int] = None, 
    attendance_date: Optional[str] = None, 
    status: Optional[str] = None
) -> dict:
    """Gets attendance records with optional filtering by student_id, date, or status.

    Args:
        student_id (int, optional): Filter by student ID.
        attendance_date (str, optional): Filter by attendance date (YYYY-MM-DD format).
        status (str, optional): Filter by attendance status ('present', 'absent', 'late').

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'records' (list[dict]) containing the attendance records if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT a.id, a.student_id, s.student_name, a.attendance_date, 
                   a.status, a.notes, a.created_at
            FROM app.attendance a
            LEFT JOIN app.students s ON a.student_id = s.student_id
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("a.student_id = :student_id")
            params["student_id"] = student_id
        
        if attendance_date is not None:
            conditions.append("a.attendance_date = :attendance_date")
            params["attendance_date"] = attendance_date
        
        if status is not None:
            conditions.append("a.status = :status")
            params["status"] = status
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY a.attendance_date DESC, s.student_name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        records = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(records)} attendance records.",
            "records": records,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving attendance records: {e}",
            "records": [],
        }
    finally:
        conn.close()


def mark_attendance(
    student_id: int, 
    attendance_date: str, 
    status: str = "present", 
    notes: Optional[str] = None
) -> dict:
    """Marks attendance for a student on a specific date.

    Args:
        student_id (int): The ID of the student.
        attendance_date (str): The date of attendance (YYYY-MM-DD format).
        status (str): The attendance status ('present', 'absent', 'late'). Defaults to 'present'.
        notes (str, optional): Additional notes about the attendance.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'attendance_id' (int) if successful.
    """
    conn = get_db_connection()
    try:
        # Check if attendance already exists for this student and date
        check_query = """
            SELECT id FROM app.attendance 
            WHERE student_id = :student_id AND attendance_date = :attendance_date
        """
        check_result = conn.execute(text(check_query), {
            "student_id": student_id,
            "attendance_date": attendance_date
        })
        existing_record = check_result.fetchone()
        
        if existing_record:
            # Update existing record
            update_query = """
                UPDATE app.attendance 
                SET status = :status, notes = :notes
                WHERE student_id = :student_id AND attendance_date = :attendance_date
                RETURNING id
            """
            params = {
                "student_id": student_id,
                "attendance_date": attendance_date,
                "status": status,
                "notes": notes
            }
            result = conn.execute(text(update_query), params)
            attendance_id = result.fetchone()[0]
            conn.commit()
            
            return {
                "success": True,
                "message": f"Attendance updated successfully for student {student_id} on {attendance_date}.",
                "attendance_id": attendance_id,
            }
        else:
            # Insert new record
            insert_query = """
                INSERT INTO app.attendance (student_id, attendance_date, status, notes)
                VALUES (:student_id, :attendance_date, :status, :notes)
                RETURNING id
            """
            params = {
                "student_id": student_id,
                "attendance_date": attendance_date,
                "status": status,
                "notes": notes
            }
            result = conn.execute(text(insert_query), params)
            attendance_id = result.fetchone()[0]
            conn.commit()
            
            return {
                "success": True,
                "message": f"Attendance marked successfully for student {student_id} on {attendance_date}.",
                "attendance_id": attendance_id,
            }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error marking attendance: {e}",
        }
    finally:
        conn.close()


def get_attendance_summary(
    student_id: Optional[int] = None, 
    start_date: Optional[str] = None, 
    end_date: Optional[str] = None
) -> dict:
    """Gets attendance summary statistics for students within a date range.

    Args:
        student_id (int, optional): Filter by student ID.
        start_date (str, optional): Start date for the summary (YYYY-MM-DD format).
        end_date (str, optional): End date for the summary (YYYY-MM-DD format).

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'summary' (list[dict]) containing attendance statistics.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT 
                a.student_id, 
                s.student_name,
                COUNT(*) as total_days,
                COUNT(CASE WHEN a.status = 'present' THEN 1 END) as present_days,
                COUNT(CASE WHEN a.status = 'absent' THEN 1 END) as absent_days,
                COUNT(CASE WHEN a.status = 'late' THEN 1 END) as late_days,
                ROUND(
                    (COUNT(CASE WHEN a.status = 'present' THEN 1 END) * 100.0 / COUNT(*)), 2
                ) as attendance_percentage
            FROM app.attendance a
            LEFT JOIN app.students s ON a.student_id = s.student_id
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("a.student_id = :student_id")
            params["student_id"] = student_id
        
        if start_date is not None:
            conditions.append("a.attendance_date >= :start_date")
            params["start_date"] = start_date
        
        if end_date is not None:
            conditions.append("a.attendance_date <= :end_date")
            params["end_date"] = end_date
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " GROUP BY a.student_id, s.student_name ORDER BY s.student_name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        summary = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved attendance summary for {len(summary)} students.",
            "summary": summary,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving attendance summary: {e}",
            "summary": [],
        }
    finally:
        conn.close()


def get_behavior_records(
    student_id: Optional[int] = None,
    logged_by: Optional[int] = None,
    source: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """Gets behavior records with optional filtering.

    Args:
        student_id (int, optional): Filter by student ID.
        logged_by (int, optional): Filter by user who logged the record.
        source (str, optional): Filter by behavior source.
        start_date (str, optional): Start date filter (YYYY-MM-DD format).
        end_date (str, optional): End date filter (YYYY-MM-DD format).

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'records' (list[dict]) containing behavior records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT br.id, br.student_id, s.student_name, br.logged_by,
                   u.name as logged_by_name, br.source, br.behaviour_type,
                   br.sentiment_score, br.comment, br.record_date, br.created_at
            FROM app.behavior_records br
            LEFT JOIN app.students s ON br.student_id = s.student_id
            LEFT JOIN app.users u ON br.logged_by = u.id
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("br.student_id = :student_id")
            params["student_id"] = student_id
        
        if logged_by is not None:
            conditions.append("br.logged_by = :logged_by")
            params["logged_by"] = logged_by
        
        if source is not None:
            conditions.append("br.source = :source")
            params["source"] = source
        
        if start_date is not None:
            conditions.append("br.record_date >= :start_date")
            params["start_date"] = start_date
        
        if end_date is not None:
            conditions.append("br.record_date <= :end_date")
            params["end_date"] = end_date
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY br.record_date DESC, br.created_at DESC"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        records = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(records)} behavior records.",
            "records": records,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving behavior records: {e}",
            "records": [],
        }
    finally:
        conn.close()


def add_behavior_record(
    student_id: int,
    source: str,
    record_date: str,
    behaviour_type: Optional[str] = None,
    sentiment_score: Optional[float] = None,
    comment: Optional[str] = None,
    logged_by: Optional[int] = None
) -> dict:
    """Adds a new behavior record for a student.

    Args:
        student_id (int): The ID of the student.
        source (str): The source of the behavior record.
        record_date (str): The date of the record (YYYY-MM-DD format).
        behaviour_type (str, optional): Type of behavior observed.
        sentiment_score (float, optional): Sentiment score (-1.0 to 1.0).
        comment (str, optional): Additional comments about the behavior.
        logged_by (int, optional): ID of the user logging the record.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'record_id' (int) if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            INSERT INTO app.behavior_records 
            (student_id, source, record_date, behaviour_type, 
             sentiment_score, comment, logged_by)
            VALUES (:student_id, :source, :record_date, :behaviour_type,
                    :sentiment_score, :comment, :logged_by)
            RETURNING id
        """
        
        params = {
            "student_id": student_id,
            "source": source,
            "record_date": record_date,
            "behaviour_type": behaviour_type,
            "sentiment_score": sentiment_score,
            "comment": comment,
            "logged_by": logged_by
        }
        
        result = conn.execute(text(query), params)
        record_id = result.fetchone()[0]
        conn.commit()
        
        return {
            "success": True,
            "message": f"Behavior record added successfully for student {student_id}.",
            "record_id": record_id,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error adding behavior record: {e}",
        }
    finally:
        conn.close()


def get_behavior_summary(
    student_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> dict:
    """Gets behavior summary statistics for students within a date range.

    Args:
        student_id (int, optional): Filter by student ID.
        start_date (str, optional): Start date (YYYY-MM-DD format).
        end_date (str, optional): End date (YYYY-MM-DD format).

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'summary' (list[dict]) containing behavior statistics.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT 
                br.student_id,
                s.student_name,
                COUNT(*) as total_records,
                AVG(br.sentiment_score) as avg_sentiment_score,
                MIN(br.sentiment_score) as min_sentiment_score,
                MAX(br.sentiment_score) as max_sentiment_score,
                COUNT(CASE WHEN br.sentiment_score > 0 THEN 1 END) as positive_records,
                COUNT(CASE WHEN br.sentiment_score < 0 THEN 1 END) as negative_records,
                COUNT(CASE WHEN br.sentiment_score = 0 THEN 1 END) as neutral_records
            FROM app.behavior_records br
            LEFT JOIN app.students s ON br.student_id = s.student_id
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("br.student_id = :student_id")
            params["student_id"] = student_id
        
        if start_date is not None:
            conditions.append("br.record_date >= :start_date")
            params["start_date"] = start_date
        
        if end_date is not None:
            conditions.append("br.record_date <= :end_date")
            params["end_date"] = end_date
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " GROUP BY br.student_id, s.student_name ORDER BY s.student_name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        summary = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved behavior summary for {len(summary)} students.",
            "summary": summary,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving behavior summary: {e}",
            "summary": [],
        }
    finally:
        conn.close()


def get_students(
    student_id: Optional[int] = None,
    student_name: Optional[str] = None,
    class_value: Optional[str] = None,
    section: Optional[str] = None,
    gender: Optional[str] = None
) -> dict:
    """Gets student records with optional filtering.

    Args:
        student_id (int, optional): Filter by student ID.
        student_name (str, optional): Filter by student name (partial match).
        class_value (str, optional): Filter by class.
        section (str, optional): Filter by section.
        gender (str, optional): Filter by gender.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'students' (list[dict]) containing student records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT id, student_id, student_name, parent_name, parent_phone,
                   class_value, section, date_of_birth, gender, 
                   created_at, updated_at
            FROM app.students
        """
        
        conditions = []
        params = {}
        
        if student_id is not None:
            conditions.append("student_id = :student_id")
            params["student_id"] = student_id
        
        if student_name is not None:
            conditions.append("student_name ILIKE :student_name")
            params["student_name"] = f"%{student_name}%"
        
        if class_value is not None:
            conditions.append("class_value = :class_value")
            params["class_value"] = class_value
        
        if section is not None:
            conditions.append("section = :section")
            params["section"] = section
        
        if gender is not None:
            conditions.append("gender = :gender")
            params["gender"] = gender
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY class_value, section, student_name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        students = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(students)} student records.",
            "students": students,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving student records: {e}",
            "students": [],
        }
    finally:
        conn.close()


def add_student(
    student_id: int,
    student_name: str,
    parent_name: str,
    class_value: str,
    section: str,
    date_of_birth: str,
    parent_phone: Optional[str] = None,
    gender: Optional[str] = None
) -> dict:
    """Adds a new student record.

    Args:
        student_id (int): Unique student ID.
        student_name (str): Full name of the student.
        parent_name (str): Name of the parent/guardian.
        class_value (str): Class/grade of the student.
        section (str): Section within the class.
        date_of_birth (str): Date of birth (YYYY-MM-DD format).
        parent_phone (str, optional): Parent's phone number.
        gender (str, optional): Gender ('male', 'female', 'other').

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'record_id' (int) if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            INSERT INTO app.students 
            (student_id, student_name, parent_name, parent_phone, 
             class_value, section, date_of_birth, gender)
            VALUES (:student_id, :student_name, :parent_name, :parent_phone,
                    :class_value, :section, :date_of_birth, :gender)
            RETURNING id
        """
        
        params = {
            "student_id": student_id,
            "student_name": student_name,
            "parent_name": parent_name,
            "parent_phone": parent_phone,
            "class_value": class_value,
            "section": section,
            "date_of_birth": date_of_birth,
            "gender": gender
        }
        
        result = conn.execute(text(query), params)
        record_id = result.fetchone()[0]
        conn.commit()
        
        return {
            "success": True,
            "message": f"Student {student_name} added successfully with ID {student_id}.",
            "record_id": record_id,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error adding student record: {e}",
        }
    finally:
        conn.close()


def update_student(
    student_id: int,
    student_name: Optional[str] = None,
    parent_name: Optional[str] = None,
    parent_phone: Optional[str] = None,
    class_value: Optional[str] = None,
    section: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    gender: Optional[str] = None
) -> dict:
    """Updates an existing student record.

    Args:
        student_id (int): The student ID to update.
        student_name (str, optional): New student name.
        parent_name (str, optional): New parent name.
        parent_phone (str, optional): New parent phone.
        class_value (str, optional): New class.
        section (str, optional): New section.
        date_of_birth (str, optional): New date of birth (YYYY-MM-DD).
        gender (str, optional): New gender ('male', 'female', 'other').

    Returns:
        dict: A dictionary with keys 'success' (bool) and 'message' (str).
    """
    conn = get_db_connection()
    try:
        # Build dynamic update query
        update_fields = []
        params = {"student_id": student_id}
        
        if student_name is not None:
            update_fields.append("student_name = :student_name")
            params["student_name"] = student_name
        
        if parent_name is not None:
            update_fields.append("parent_name = :parent_name")
            params["parent_name"] = parent_name
        
        if parent_phone is not None:
            update_fields.append("parent_phone = :parent_phone")
            params["parent_phone"] = parent_phone
        
        if class_value is not None:
            update_fields.append("class_value = :class_value")
            params["class_value"] = class_value
        
        if section is not None:
            update_fields.append("section = :section")
            params["section"] = section
        
        if date_of_birth is not None:
            update_fields.append("date_of_birth = :date_of_birth")
            params["date_of_birth"] = date_of_birth
        
        if gender is not None:
            update_fields.append("gender = :gender")
            params["gender"] = gender
        
        if not update_fields:
            return {
                "success": False,
                "message": "No fields provided for update.",
            }
        
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"""
            UPDATE app.students 
            SET {', '.join(update_fields)}
            WHERE student_id = :student_id
        """
        
        result = conn.execute(text(query), params)
        rows_updated = result.rowcount
        conn.commit()
        
        if rows_updated == 0:
            return {
                "success": False,
                "message": f"No student found with ID {student_id}.",
            }
        
        return {
            "success": True,
            "message": f"Student record updated successfully for ID {student_id}.",
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error updating student record: {e}",
        }
    finally:
        conn.close()


def get_students_by_class(class_value: str, section: Optional[str] = None) -> dict:
    """Gets all students in a specific class and optionally section.

    Args:
        class_value (str): The class to filter by.
        section (str, optional): The section to filter by.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'students' (list[dict]) containing student records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT id, student_id, student_name, parent_name, parent_phone,
                   class_value, section, date_of_birth, gender, 
                   created_at, updated_at
            FROM app.students
            WHERE class_value = :class_value
        """
        
        params = {"class_value": class_value}
        
        if section is not None:
            query += " AND section = :section"
            params["section"] = section
        
        query += " ORDER BY student_name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        students = [dict(zip(columns, row)) for row in result.fetchall()]
        
        class_section = f"{class_value}-{section}" if section else class_value
        
        return {
            "success": True,
            "message": f"Retrieved {len(students)} students from {class_section}.",
            "students": students,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving students by class: {e}",
            "students": [],
        }
    finally:
        conn.close()


def get_users(
    user_id: Optional[int] = None,
    name: Optional[str] = None,
    email: Optional[str] = None,
    role: Optional[str] = None,
    student_id: Optional[int] = None,
    subject: Optional[str] = None
) -> dict:
    """Gets user records with optional filtering.

    Args:
        user_id (int, optional): Filter by user ID.
        name (str, optional): Filter by user name (partial match).
        email (str, optional): Filter by email address.
        role (str, optional): Filter by user role ('teacher', 'parent', 'admin').
        student_id (int, optional): Filter by associated student ID.
        subject (str, optional): Filter by subject (for teachers).

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'users' (list[dict]) containing user records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT u.id, u.name, u.email, u.role, u.language, u.phone,
                   u.student_id, s.student_name, u.subject, u.created_at, u.updated_at
            FROM app.users u
            LEFT JOIN app.students s ON u.student_id = s.student_id
        """
        
        conditions = []
        params = {}
        
        if user_id is not None:
            conditions.append("u.id = :user_id")
            params["user_id"] = user_id
        
        if name is not None:
            conditions.append("u.name ILIKE :name")
            params["name"] = f"%{name}%"
        
        if email is not None:
            conditions.append("u.email = :email")
            params["email"] = email
        
        if role is not None:
            conditions.append("u.role = :role")
            params["role"] = role
        
        if student_id is not None:
            conditions.append("u.student_id = :student_id")
            params["student_id"] = student_id
        
        if subject is not None:
            conditions.append("u.subject ILIKE :subject")
            params["subject"] = f"%{subject}%"
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY u.role, u.name"
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        users = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(users)} user records.",
            "users": users,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving user records: {e}",
            "users": [],
        }
    finally:
        conn.close()


def add_user(
    name: str,
    email: str,
    password_hash: str,
    role: str = "parent",
    language: str = "en",
    phone: Optional[str] = None,
    student_id: Optional[int] = None,
    subject: Optional[str] = None
) -> dict:
    """Adds a new user record.

    Args:
        name (str): Full name of the user.
        email (str): Email address (must be unique).
        password_hash (str): Hashed password.
        role (str): User role ('teacher', 'parent', 'admin'). Defaults to 'parent'.
        language (str): Preferred language code. Defaults to 'en'.
        phone (str, optional): Phone number.
        student_id (int, optional): Associated student ID (for parents).
        subject (str, optional): Subject taught (for teachers).

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'user_id' (int) if successful.
    """
    conn = get_db_connection()
    try:
        query = """
            INSERT INTO app.users 
            (name, email, password_hash, role, language, phone, student_id, subject)
            VALUES (:name, :email, :password_hash, :role, :language, :phone, :student_id, :subject)
            RETURNING id
        """
        
        params = {
            "name": name,
            "email": email,
            "password_hash": password_hash,
            "role": role,
            "language": language,
            "phone": phone,
            "student_id": student_id,
            "subject": subject
        }
        
        result = conn.execute(text(query), params)
        user_id = result.fetchone()[0]
        conn.commit()
        
        return {
            "success": True,
            "message": f"User {name} added successfully with ID {user_id}.",
            "user_id": user_id,
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error adding user record: {e}",
        }
    finally:
        conn.close()


def update_user(
    user_id: int,
    name: Optional[str] = None,
    email: Optional[str] = None,
    password_hash: Optional[str] = None,
    role: Optional[str] = None,
    language: Optional[str] = None,
    phone: Optional[str] = None,
    student_id: Optional[int] = None,
    subject: Optional[str] = None
) -> dict:
    """Updates an existing user record.

    Args:
        user_id (int): The user ID to update.
        name (str, optional): New user name.
        email (str, optional): New email address.
        password_hash (str, optional): New password hash.
        role (str, optional): New user role.
        language (str, optional): New language preference.
        phone (str, optional): New phone number.
        student_id (int, optional): New associated student ID.
        subject (str, optional): New subject (for teachers).

    Returns:
        dict: A dictionary with keys 'success' (bool) and 'message' (str).
    """
    conn = get_db_connection()
    try:
        # Build dynamic update query
        update_fields = []
        params = {"user_id": user_id}
        
        if name is not None:
            update_fields.append("name = :name")
            params["name"] = name
        
        if email is not None:
            update_fields.append("email = :email")
            params["email"] = email
        
        if password_hash is not None:
            update_fields.append("password_hash = :password_hash")
            params["password_hash"] = password_hash
        
        if role is not None:
            update_fields.append("role = :role")
            params["role"] = role
        
        if language is not None:
            update_fields.append("language = :language")
            params["language"] = language
        
        if phone is not None:
            update_fields.append("phone = :phone")
            params["phone"] = phone
        
        if student_id is not None:
            update_fields.append("student_id = :student_id")
            params["student_id"] = student_id
        
        if subject is not None:
            update_fields.append("subject = :subject")
            params["subject"] = subject
        
        if not update_fields:
            return {
                "success": False,
                "message": "No fields provided for update.",
            }
        
        update_fields.append("updated_at = CURRENT_TIMESTAMP")
        
        query = f"""
            UPDATE app.users 
            SET {', '.join(update_fields)}
            WHERE id = :user_id
        """
        
        result = conn.execute(text(query), params)
        rows_updated = result.rowcount
        conn.commit()
        
        if rows_updated == 0:
            return {
                "success": False,
                "message": f"No user found with ID {user_id}.",
            }
        
        return {
            "success": True,
            "message": f"User record updated successfully for ID {user_id}.",
        }
    except Exception as e:
        conn.rollback()
        return {
            "success": False,
            "message": f"Error updating user record: {e}",
        }
    finally:
        conn.close()


def get_users_by_role(role: str) -> dict:
    """Gets all users with a specific role.

    Args:
        role (str): The role to filter by ('teacher', 'parent', 'admin').

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'users' (list[dict]) containing user records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT u.id, u.name, u.email, u.role, u.language, u.phone,
                   u.student_id, s.student_name, u.subject, u.created_at, u.updated_at
            FROM app.users u
            LEFT JOIN app.students s ON u.student_id = s.student_id
            WHERE u.role = :role
            ORDER BY u.name
        """
        
        params = {"role": role}
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        users = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(users)} users with role '{role}'.",
            "users": users,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving users by role: {e}",
            "users": [],
        }
    finally:
        conn.close()


def get_teachers_by_subject(subject: str) -> dict:
    """Gets all teachers who teach a specific subject.

    Args:
        subject (str): The subject to filter by.

    Returns:
        dict: A dictionary with keys 'success' (bool), 'message' (str),
              and 'teachers' (list[dict]) containing teacher records.
    """
    conn = get_db_connection()
    try:
        query = """
            SELECT u.id, u.name, u.email, u.phone, u.subject, u.language,
                   u.created_at, u.updated_at
            FROM app.users u
            WHERE u.role = 'teacher' AND u.subject ILIKE :subject
            ORDER BY u.name
        """
        
        params = {"subject": f"%{subject}%"}
        
        result = conn.execute(text(query), params)
        columns = result.keys()
        teachers = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return {
            "success": True,
            "message": f"Retrieved {len(teachers)} teachers for subject '{subject}'.",
            "teachers": teachers,
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Error retrieving teachers by subject: {e}",
            "teachers": [],
        }
    finally:
        conn.close()


# --- MCP Server Setup ---
logging.info(
    "Creating MCP Server instance for PostgreSQL DB..."
)  
app = Server("postgresql-db-mcp-server")

# Wrap database utility functions as ADK FunctionTools
ADK_DB_TOOLS = {
    "list_db_tables": FunctionTool(func=list_db_tables),
    "get_table_schema": FunctionTool(func=get_table_schema),
    "query_db_table": FunctionTool(func=query_db_table),
    "insert_data": FunctionTool(func=insert_data),
    "delete_data": FunctionTool(func=delete_data),
    "get_academic_records": FunctionTool(func=get_academic_records),
    "add_academic_record": FunctionTool(func=add_academic_record),
    "get_attendance_records": FunctionTool(func=get_attendance_records),
    "mark_attendance": FunctionTool(func=mark_attendance),
    "get_attendance_summary": FunctionTool(func=get_attendance_summary),
    "get_behavior_records": FunctionTool(func=get_behavior_records),
    "add_behavior_record": FunctionTool(func=add_behavior_record),
    "get_behavior_summary": FunctionTool(func=get_behavior_summary),
    "get_students": FunctionTool(func=get_students),
    "add_student": FunctionTool(func=add_student),
    "update_student": FunctionTool(func=update_student),
    "get_students_by_class": FunctionTool(func=get_students_by_class),
    "get_users": FunctionTool(func=get_users),
    "add_user": FunctionTool(func=add_user),
    "update_user": FunctionTool(func=update_user),
    "get_users_by_role": FunctionTool(func=get_users_by_role),
    "get_teachers_by_subject": FunctionTool(func=get_teachers_by_subject),
}


@app.list_tools()
async def list_mcp_tools() -> list[mcp_types.Tool]:
    """MCP handler to list tools this server exposes."""
    logging.info(
        "MCP Server: Received list_tools request."
    )  # Changed print to logging.info
    mcp_tools_list = []
    for tool_name, adk_tool_instance in ADK_DB_TOOLS.items():
        if not adk_tool_instance.name:
            adk_tool_instance.name = tool_name

        mcp_tool_schema = adk_to_mcp_tool_type(adk_tool_instance)
        logging.info(  # Changed print to logging.info
            f"MCP Server: Advertising tool: {mcp_tool_schema.name}, InputSchema: {mcp_tool_schema.inputSchema}"
        )
        mcp_tools_list.append(mcp_tool_schema)
    return mcp_tools_list


@app.call_tool()
async def call_mcp_tool(name: str, arguments: dict) -> list[mcp_types.TextContent]:
    """MCP handler to execute a tool call requested by an MCP client."""
    logging.info(
        f"MCP Server: Received call_tool request for '{name}' with args: {arguments}"
    )  # Changed print to logging.info

    if name in ADK_DB_TOOLS:
        adk_tool_instance = ADK_DB_TOOLS[name]
        try:
            adk_tool_response = await adk_tool_instance.run_async(
                args=arguments,
                tool_context=None,  # type: ignore
            )
            logging.info(  # Changed print to logging.info
                f"MCP Server: ADK tool '{name}' executed. Response: {adk_tool_response}"
            )
            response_text = json.dumps(adk_tool_response, indent=2, default=json_serializer)
            return [mcp_types.TextContent(type="text", text=response_text)]

        except Exception as e:
            logging.error(
                f"MCP Server: Error executing ADK tool '{name}': {e}", exc_info=True
            )  # Changed print to logging.error, added exc_info
            error_payload = {
                "success": False,
                "message": f"Failed to execute tool '{name}': {str(e)}",
            }
            error_text = json.dumps(error_payload)
            return [mcp_types.TextContent(type="text", text=error_text)]
    else:
        logging.warning(
            f"MCP Server: Tool '{name}' not found/exposed by this server."
        )  # Changed print to logging.warning
        error_payload = {
            "success": False,
            "message": f"Tool '{name}' not implemented by this server.",
        }
        error_text = json.dumps(error_payload)
        return [mcp_types.TextContent(type="text", text=error_text)]


# --- MCP Server Runner ---
async def run_mcp_stdio_server():
    """Runs the MCP server, listening for connections over standard input/output."""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        logging.info(
            "MCP Stdio Server: Starting handshake with client..."
        )  # Changed print to logging.info
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=app.name,
                server_version="0.1.0",
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
        logging.info(
            "MCP Stdio Server: Run loop finished or client disconnected."
        )  # Changed print to logging.info


if __name__ == "__main__":
    logging.info(
        "Launching PostgreSQL DB MCP Server via stdio..."
    )
    try:
        asyncio.run(run_mcp_stdio_server())
    except KeyboardInterrupt:
        logging.info(
            "\nMCP Server (stdio) stopped by user."
        )
    except Exception as e:
        logging.critical(
            f"MCP Server (stdio) encountered an unhandled error: {e}", exc_info=True
        )
    finally:
        logging.info(
            "MCP Server (stdio) process exiting."
        )

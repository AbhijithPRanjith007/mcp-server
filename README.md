# MCP Server for PostgreSQL Database Operations

This MCP (Model Context Protocol) server provides database access tools for the Teacher Assistant ADK system. It exposes PostgreSQL database operations as MCP tools that can be used by AI agents to interact with student data, attendance records, academic records, and behavior tracking.

## Overview

The MCP server acts as a bridge between the AI agent and the PostgreSQL database, providing secure and structured access to educational data through a standardized protocol.

## Features

**Database Connection Management**: Secure connection to Google Cloud SQL PostgreSQL
**Student Management**: CRUD operations for student records
**Academic Records**: Grade and academic performance tracking
**Attendance Tracking**: Student attendance management and reporting
**Behavior Records**: Behavioral observation and sentiment tracking
**User Management**: Teacher, parent, and admin user management
**Dynamic Querying**: Flexible database querying with filtering options
**Comprehensive Logging**: Detailed activity logging for debugging and monitoring

## Database Schema

The server connects to a PostgreSQL database with the following main tables:

### Core Tables
app.students - Student information and demographics
app.users - Teachers, parents, and admin users
app.academic_records - Grades and academic performance
app.attendance - Daily attendance records
app.behavior_records - Behavioral observations and sentiment analysis

## Available MCP Tools

### General Database Operations
list_db_tables - List all available database tables
get_table_schema - Get column information for a specific table
query_db_table - Execute custom queries with conditions
insert_data - Insert new records into any table
delete_data - Delete records based on conditions

### Student Management
get_students - Retrieve student records with filtering
add_student - Add new student records
update_student - Update existing student information
get_students_by_class - Get all students in a specific class/section

### Academic Records
get_academic_records - Retrieve academic performance data
add_academic_record - Record new grades or academic achievements

### Attendance Management
get_attendance_records - Retrieve attendance data
mark_attendance - Record student attendance
get_attendance_summary - Generate attendance statistics

### Behavior Tracking
get_behavior_records - Retrieve behavioral observations
add_behavior_record - Log new behavior records
get_behavior_summary - Generate behavior analytics

### User Management
get_users - Retrieve user accounts
add_user - Create new user accounts
update_user - Update user information
get_users_by_role - Filter users by role (teacher/parent/admin)
get_teachers_by_subject - Find teachers by subject area

## Configuration

### Database Connection
The server connects to a PostgreSQL database with the following configuration:

python
# Database credentials (update in server.py)
username = "your_username"
password = "your_password"
host = "your_host"
port = "5432"
database = "student"

### Environment Setup
1. Ensure PostgreSQL connectivity
2. Verify database schema exists in app schema
3. Configure appropriate database permissions

## Installation and Setup

### Prerequisites
Python 3.8+
PostgreSQL database access
Required Python packages (see requirements below)

### Dependencies
bash
pip install sqlalchemy psycopg2-binary python-dotenv google-adk-agents mcp

### Running the MCP Server

#### As a Standalone Server
bash
cd teacher_assistant
python server.py

#### Integration with ADK Agent
The MCP server is designed to be integrated with the main Teacher Assistant ADK system. The agent can connect to this MCP server to access database functionality.

## Usage Examples

### Basic Database Query
python
# List all tables
await call_tool("list_db_tables", {"dummy_param": "required"})

# Get student information
await call_tool("get_students", {
    "class_value": "10",
    "section": "A"
})

### Academic Record Management
python
# Add a new grade
await call_tool("add_academic_record", {
    "student_id": 12345,
    "subject": "Mathematics",
    "grade": "A",
    "record_date": "2024-01-15",
    "teacher_id": 1
})

# Get academic records for a student
await call_tool("get_academic_records", {
    "student_id": 12345,
    "subject": "Mathematics"
})

### Attendance Tracking
python
# Mark attendance
await call_tool("mark_attendance", {
    "student_id": 12345,
    "attendance_date": "2024-01-15",
    "status": "present"
})

# Get attendance summary
await call_tool("get_attendance_summary", {
    "student_id": 12345,
    "start_date": "2024-01-01",
    "end_date": "2024-01-31"
})

## Security Considerations

**Database Credentials**: Store credentials securely, consider using environment variables
**Input Validation**: All user inputs are validated and parameterized to prevent SQL injection
**Schema Isolation**: Uses app schema for data isolation
**Connection Management**: Proper connection lifecycle management with cleanup

## Logging and Monitoring

The server includes comprehensive logging:

python
# Log file location
LOG_FILE_PATH = "teacher_assistant/mcp_server_activity.log"

# Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL

Logs include:
Tool execution requests and responses
Database connection status
Error details with stack traces
Performance metrics

## Error Handling

The server implements robust error handling:

**Database Connection Errors**: Graceful handling of connection issues
**Invalid Parameters**: Validation and user-friendly error messages
**SQL Errors**: Safe error reporting without exposing sensitive information
**Tool Execution Errors**: Structured error responses for debugging

## Database Schema Requirements

Ensure your PostgreSQL database has the following structure:

sql
-- Example table structures (adjust as needed)

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.students (
    id SERIAL PRIMARY KEY,
    student_id INTEGER UNIQUE NOT NULL,
    student_name VARCHAR(255) NOT NULL,
    parent_name VARCHAR(255),
    parent_phone VARCHAR(20),
    class_value VARCHAR(10),
    section VARCHAR(10),
    date_of_birth DATE,
    gender VARCHAR(10),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Additional tables: users, academic_records, attendance, behavior_records

## Integration with Main Application

The MCP server is designed to work with the main Teacher Assistant ADK application:

1. **Agent Integration**: The main agent connects to this MCP server for database operations
2. **Tool Discovery**: Agent automatically discovers available database tools
3. **Secure Communication**: Uses MCP protocol for structured communication
4. **Data Consistency**: Ensures data integrity across all operations

## Troubleshooting

### Common Issues

1. **Database Connection Failed**
   - Verify database credentials
   - Check network connectivity
   - Ensure PostgreSQL service is running

2. **Tool Not Found**
   - Verify tool name matches exactly
   - Check tool registration in ADK_DB_TOOLS

3. **Permission Denied**
   - Verify database user permissions
   - Check schema access rights

4. **Invalid Parameters**
   - Review tool parameter requirements
   - Validate data types and formats

### Debug Mode
Enable detailed logging by setting log level to DEBUG:

python
logging.basicConfig(level=logging.DEBUG)

## Contributing

When adding new database tools:

1. Create the function with proper type hints and docstrings
2. Add input validation and error handling
3. Register the tool in ADK_DB_TOOLS
4. Update this documentation
5. Add appropriate tests

## License

This MCP server is part of the Teacher Assistant ADK project. See main project license for details.

## Support

For issues specific to the MCP server:
1. Check the log file for detailed error information
2. Verify database connectivity and permissions
3. Ensure all required dependencies are installed
4. Review parameter formats and requirements

For general project support, refer to the main project documentation.

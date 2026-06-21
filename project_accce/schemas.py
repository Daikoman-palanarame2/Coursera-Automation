from typing import List, Optional
from pydantic import BaseModel, Field

class SyllabusNode(BaseModel):
    id: str = Field(..., description="Unique ID of the syllabus node")
    type: str = Field(..., description="Type of node: video, reading, quiz, lab, or discussion")
    is_completed: bool = Field(default=False, description="Completion status of the node")
    next_node_id: Optional[str] = Field(None, description="ID of the next node in syllabus sequence")
    name: Optional[str] = Field(None, description="Human-readable title/name of the syllabus node")
    module_name: Optional[str] = Field(None, description="Name of the module/week this node belongs to")

class QuizPayload(BaseModel):
    question_text: str = Field(..., description="Extracted raw text of the question")
    question_type: str = Field(..., description="Type of question: multiple_choice, checkbox, or text")
    options_array: List[str] = Field(default_factory=list, description="Array of alternative choices raw text")
    input_element_selectors: List[str] = Field(default_factory=list, description="CSS selectors corresponding to the choices input elements")

class GradeBookState(BaseModel):
    course_id: str = Field(..., description="Unique course identifier string")
    total_progress_percentage: float = Field(..., ge=0.0, le=100.0, description="Overall course completion percentage")
    mandatory_modules_passed: List[str] = Field(..., description="IDs of mandatory modules that have been completed and passed")

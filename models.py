from typing import Optional, Dict
from __future__ import annotations
class BoundingBox:
    def __init__(self,x:float,y:float,width:float,height:float):
        self.x = x
        self.y = y
        self.width = width
        self.height = height
    def center(self)->tuple[float,float]:
        return (self.x + self.width / 2, self.y + self.height / 2)
    def contains_point(self,x:float,y:float)->bool:
        
        return self.x<=x<=self.x+self.width and self.y<=y<=self.y+self.height
    def overlaps(self,other:BoundingBox)->bool:
        return self.x<other.x+other.width and self.x+self.width>other.x and self.y<other.y+other.height and self.y+self.height>other.y
    def area(self)->float:
        return self.width * self.height
class Element:
    def __init__(self,index:int, node_int:int, backend_node_id:int, tag:str,role:Optional[str],bounding_box:Optional[BoundingBox],parent_index:Optional[int],is_visible:bool,is_interactive:bool,attributes:Dict[str,str], paint_order:Optional[int]):
        self.index = index
        self.node_int = node_int
        self.backend_node_id = backend_node_id
        self.tag = tag
        self.role = role
        self.bounding_box = bounding_box
        self.parent_index = parent_index
        self.is_visible = is_visible
        self.is_interactive = is_interactive
        self.attributes = attributes
        self.paint_order = paint_order
        
class FinalDOM:
    def __init__(self, elements:dict[int,Element],dpr:float,viewport_width:int,viewport_height:int):
        self.elements = elements
        self.dpr = dpr
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
    def get_interactive_elements(self)->list[Element]:
        return [element for element in self.elements.values() if element.is_interactive]
    def get_visible_elements(self)->list[Element]:
        return [element for element in self.elements.values() if element.is_visible]
    def get_elements_by_role(self,role:str)->list[Element]:
        return [element for element in self.elements.values() if element.role == role]
    def get_elements_by_tag(self,tag:str)->list[Element]:
        return [element for element in self.elements.values() if element.tag == tag]
    def get_elements_by_attribute(self,attribute:str)->list[Element]:
        return [element for element in self.elements.values() if attribute in element.attributes]
    def get_elements_by_paint_order(self,paint_order:int)->list[Element]:
        return [element for element in self.elements.values() if element.paint_order == paint_order]
    def to_dict(self)->dict[int,Element]:
        return {element.index: element for element in self.elements.values()}
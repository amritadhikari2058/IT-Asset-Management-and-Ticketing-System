import ast
import os

monitoring_dir = r"D:\IT-Asset-Management-and-Ticketing-System\backend\monitoring"

results = []

test_files = sorted([f for f in os.listdir(monitoring_dir) if f.startswith("test_") and f.endswith(".py")])

for tf in test_files:
    filepath = os.path.join(monitoring_dir, tf)
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    
    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        results.append(f"{tf}: SYNTAX ERROR - {e}")
        continue
    
    file_size = len(content.encode("utf-8"))
    line_count = len(content.splitlines())
    
    class TestVisitor(ast.NodeVisitor):
        def __init__(self):
            self.classes = []
            self.total_methods = 0
            self.pass_methods = []
            self.assert_true_methods = []
            self.no_assert_methods = []
        
        def visit_ClassDef(self, node):
            class_info = {
                "name": node.name,
                "base": [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
                "methods": []
            }
            
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    method_name = item.name
                    method_info = {"name": method_name, "decorators": [], "has_pass": False, "has_assert_true": False, "has_no_assert": False}
                    
                    for dec in item.decorator_list:
                        if isinstance(dec, ast.Decorator):
                            method_info["decorators"].append(ast.unparse(dec) if hasattr(ast, 'unparse') else str(dec))
                        else:
                            method_info["decorators"].append(str(dec))
                    
                    # Check for pass
                    if len(item.body) == 1 and isinstance(item.body[0], ast.Pass):
                        method_info["has_pass"] = True
                    
                    # Check for assertTrue(True)
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            if isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr == "assertTrue":
                                if isinstance(stmt.value.args[0], ast.Constant) and stmt.value.args[0].value is True:
                                    method_info["has_assert_true"] = True
                    
                    # Check for methods with no meaningful assertions
                    has_meaningful_assertion = False
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                            if isinstance(stmt.value.func, ast.Attribute) and stmt.value.func.attr in ("assertEqual", "assertTrue", "assertFalse", "assertIn", "assertRaises", "assertIsNotNone", "assertIsNone"):
                                has_meaningful_assertion = True
                                break
                            # Check for API/service calls
                            if isinstance(stmt.value.func, ast.Name):
                                # Could be a model method or service call
                                pass
                    
                    if not has_meaningful_assertion:
                        method_info["has_no_assert"] = True
                    
                    class_info["methods"].append(method_info)
                    self.total_methods += 1
            
            self.classes.append(class_info)
            self.generic_visit(node)
    
    visitor = TestVisitor()
    visitor.visit(tree)
    
    # Report
    results.append(f"=== {tf} ===")
    results.append(f"  File size: {file_size} bytes")
    results.append(f"  Line count: {line_count}")
    results.append(f"  Total test methods: {visitor.total_methods}")
    
    for cls in visitor.classes:
        results.append(f"  Class: {cls['name']} (bases: {cls['base']})")
        for method in cls["methods"]:
            issues = []
            if method["has_pass"]:
                issues.append("  -> has 'pass'")
            if method["has_assert_true"]:
                issues.append("  -> has 'self.assertTrue(True)'")
            if method["has_no_assert"]:
                issues.append("  -> weak assertion (no meaningful assertion)")
            if not any([method["has_pass"], method["has_assert_true"], method["has_no_assert"]]):
                issues.append("  -> real test")
            results.append(f"    {method['name']} ({', '.join(issues)})")
    
    results.append("")

with open("inventory_output.txt", "w") as f:
    f.write("\n".join(results))

print("Inventory complete. Output saved to inventory_output.txt")
print(f"Total test methods across all files: {sum(len(c['methods']) for tf in test_files for c in [TestVisitor()] for _ in [c.visit(ast.parse(open(os.path.join(monitoring_dir, tf), 'r').read()))] for _ in [1]])}")
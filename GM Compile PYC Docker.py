import os
import shutil
import subprocess
import sys
import re
from pathlib import Path

class PythonCompiler:
    def __init__(self, source_dir):
        self.source_dir = os.path.abspath(source_dir)
        self.python_versions = {
            '2.7': 'python:2.7-slim',
            '3.7': 'python:3.7-slim',
            '3.9': 'python:3.9-slim',
            '3.10': 'python:3.10-slim',
            '3.11': 'python:3.11-slim'
        }
        print(f"Initialized compiler with source directory: {self.source_dir}")

    def check_3to2(self):
        """Ensure 3to2 is installed on the system, and install it if missing."""
        try:
            import lib3to2
            print("3to2 is installed.")
        except ImportError:
            print("3to2 is not installed. Installing...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', '3to2'], check=True)
            print("3to2 installed successfully.")

    def prepare_source_files(self, version):
        """Prepare source files and convert to Python 2.7 if necessary."""
        src_dir = os.path.join(self.source_dir, "src")
        if os.path.exists(src_dir):
            shutil.rmtree(src_dir)
        os.makedirs(src_dir, exist_ok=True)

        for file_name in os.listdir(self.source_dir):
            if file_name.endswith(".py"):
                file_path = os.path.join(self.source_dir, file_name)
                target_path = os.path.join(src_dir, file_name)

                f = shutil.copy(file_path, target_path)
                
                # If targeting Python 2.7, convert each file and save it in `src`
                if version == '2.7':
                    self.convert_to_python2(f)
                    
        print(f"Prepared source files in {src_dir} for Docker")

    def convert_to_python2(self, source_path):
        """Convert a Python 3 file to Python 2 compatible syntax using 3to2 and f-string conversion."""
        print(f"Converting {source_path} to Python 2.7 compatible code...")

        # Detect and convert f-strings
        def convert_fstring_to_format(content):
            # Regex pattern to match f-strings with placeholders and optional format specifiers
            pattern = r'f"([^"]*)\{([^:}]+)(:[^}]+)?\}([^"]*)"'
            
            def replacer(match):
                before_text = match.group(1)  # Text before the variable
                variable = match.group(2)     # Variable inside {}
                format_spec = match.group(3)  # Format specifier, e.g., :.2f
                after_text = match.group(4)   # Text after variable

                # If there's a format specifier, include it in the placeholder
                if format_spec:
                    format_string = f"{{{variable}{format_spec}}}"
                else:
                    format_string = f"{{{variable}}}"
                
                # Construct the final replacement string with .format() call
                return f'"{before_text}{format_string}{after_text}".format({variable})'

            # Apply the replacer function to all matches in the content
            result = re.sub(pattern, replacer, content)
            
            return result
    
        # Step 1: Detect and convert f-strings
        with open(source_path, 'r') as file:
            content = file.read()
        
        modified_content = convert_fstring_to_format(content)
        
        # # Step 2: Overwrite the original file with the modified content
        with open(source_path, 'w') as file:
            file.write(modified_content)

        # Step 3: Apply lib3to2 transformations
        try:
            from lib3to2.main import main as lib3to2_main
            # Prepare arguments for the main function
            args = [
                'lib3to2',  # Placeholder for the script name
                '-w',       # Write the changes to the file
                source_path # Path of the file to convert
            ]
            # Temporarily override sys.argv to pass arguments to lib3to2's main function
            original_argv = sys.argv
            sys.argv = args
            lib3to2_main("lib3to2.fixes")
            print(f"Converted {source_path} to Python 2.7 compatible code.")
        except Exception as e:
            print(f"Error converting {source_path} to Python 2.7: {e}")
            raise
        finally:
            # Restore the original sys.argv
            sys.argv = original_argv        

    def build_docker_image(self, version):
        image_name = f"pycompiler_{version.replace('.', '')}"

        # Check if the image already exists
        image_exists = subprocess.run(
            ['docker', 'images', '-q', image_name],
            capture_output=True,
            text=True
        ).stdout.strip()

        # Only build the image if it doesn’t exist
        if not image_exists:
            print(f"Building Docker image: {image_name}")
            dockerfile_content = f"""FROM {self.python_versions[version]}
WORKDIR /app
RUN mkdir /app/src
"""
            dockerfile_path = f"Dockerfile-{version}"
            with open(dockerfile_path, 'w') as f:
                f.write(dockerfile_content)
            
            try:
                subprocess.run(['docker', 'build', '-f', dockerfile_path, '-t', image_name, self.source_dir], check=True)
                print(f"Docker image {image_name} built successfully")
            except subprocess.CalledProcessError as e:
                print(f"Docker build error for {version}: {e}")
                raise
            finally:
                os.remove(dockerfile_path)
                print(f"Removed Dockerfile for Python {version}")
        else:
            print(f"Docker image {image_name} already exists. Skipping build.")

    def compile_for_version(self, version):
        print(f"\n{'='*50}\nStarting compilation for Python {version}\n{'='*50}")

        output_dir = os.path.join(self.source_dir, f'python{version}libs')
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        image_name = f"pycompiler_{version.replace('.', '')}"
        container_name = f"pycompiler_container_{version.replace('.', '')}"

        try:
            # Run Docker container with mounted `src/` folder for latest files
            print(f"Running container: {container_name}")
            subprocess.run([
                'docker', 'run', '--name', container_name, 
                '-v', f"{os.path.join(self.source_dir, 'src')}:/app/src",  # Mount the latest `src` files
                image_name, 
                'find', '/app/src', '-name', '*.py', '-exec', 'python', '-m', 'py_compile', '{}', ';'
            ], check=True)

            # Copy compiled .pyc files from container
            print("Copying compiled files...")
            subprocess.run(['docker', 'cp', f"{container_name}:/app/src", output_dir], check=True)

            # Organize .pyc files correctly in output directory
            self._organize_pyc_files(output_dir)

        except subprocess.CalledProcessError as e:
            print(f"Error during Docker operations for Python {version}: {e}")
        finally:
            # Clean up Docker container (but not image)
            print("Cleaning up Docker container and files...")
            subprocess.run(['docker', 'rm', '-f', container_name], check=False)
            print("Container cleanup completed")

    def _organize_pyc_files(self, output_dir):
        print("Organizing .pyc files...")
        for root, _, files in os.walk(output_dir):
            for file in files:
                if file.endswith('.pyc'):
                    new_file_name = file.split('.')[0] + '.pyc'
                    shutil.move(os.path.join(root, file), os.path.join(output_dir, new_file_name))

        for item in os.listdir(output_dir):
            item_path = os.path.join(output_dir, item)
            if os.path.isdir(item_path):
                shutil.rmtree(item_path)

    def cleanup_pycache(self):
        print("Cleaning up __pycache__ directories...")
        for root, dirs, _ in os.walk(self.source_dir):
            if '__pycache__' in dirs:
                shutil.rmtree(os.path.join(root, '__pycache__'))

    def cleanup_src(self):
        src_dir = os.path.join(self.source_dir, "src")
        if os.path.exists(src_dir):
            shutil.rmtree(src_dir)
            print("Removed src directory")

def main():
    print("Python Files Compiler using Docker\n" + "="*40)
    source_dir = input("Enter the directory containing Python files to compile: ").strip()

    if not os.path.isdir(source_dir):
        print("Error: Invalid directory path!")
        sys.exit(1)

    # Initialize compiler
    compiler = PythonCompiler(source_dir)

    # Check and install 3to2 if necessary
    compiler.check_3to2()

    # Process each Python version separately
    for version in compiler.python_versions.keys():
        # Prepare source files and handle Python 3 to 2 conversion if needed
        compiler.prepare_source_files(version)

        # Build Docker image if needed
        compiler.build_docker_image(version)

        # Compile files for the specific version
        try:
            compiler.compile_for_version(version)
            print(f"Successfully compiled for Python {version}")
        except Exception as e:
            print(f"Failed to compile for Python {version}: {e}")

    # Final cleanup of __pycache__ directories and remove `src`
    compiler.cleanup_pycache()
    compiler.cleanup_src()

    print("\nCompilation complete! Check the version-specific directories for .pyc files.")

if __name__ == "__main__":
    main()

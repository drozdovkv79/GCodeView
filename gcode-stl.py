# Import necessary modules for file handling, regular expressions, and numerical operations
import os  # For file system operations like checking file paths
import re  # For pattern matching and parsing G-code lines
import tkinter as tk  # For creating GUI elements
from tkinter import (  # Additional GUI elements for pop-ups and scrollable text boxes
    messagebox,
    scrolledtext,
)

import matplotlib.pyplot as plt  # For plotting data
import numpy as np  # For numerical calculations and array manipulations
from matplotlib.widgets import Slider  # For interactive sliders in plots
from mpl_toolkits.mplot3d import Axes3D  # For 3D plotting support
from stl import mesh  # Import again for convenience, allows shorter syntax
from stl import mesh as Mesh  # For working with STL mesh files
from tkinterdnd2 import (  # For drag-and-drop file functionality in tkinter
    DND_FILES,
    TkinterDnD,
)


# Define a class to handle G-code processing and operations
class GcodeProcessor:
    def __init__(self):
        # Initialize an empty string to hold the G-code data
        self.gcode = ""

    # Method to read G-code input from a file
    def input_from_file(self):
        # Prompt the user to enter the path to a .gcode file
        file_path = input("Enter the path to your .gcode file: ")

        # Check if the entered path exists and ends with '.gcode' to ensure it's a valid G-code file
        if os.path.exists(file_path) and file_path.endswith(".gcode"):
            # Open the file in read mode and load all lines into the gcode attribute
            with open(file_path, "r") as file:
                self.gcode = file.readlines()
            print("G-code file successfully read.")  # Confirm successful file reading
        else:
            # If file path is invalid, notify the user and set gcode to None
            print("Invalid file path or file type.")
            self.gcode = None

    # String Search functions
    # Search for the number of layers
    # Define a method to calculate the maximum height of the layers from G-code
    def sum_layer_heights(self):
        # Initialize maximum height to zero
        max_height = 0.0

        # Iterate through each line in the G-code
        for line in self.gcode:
            # Check if the line contains "max_z_height:" indicating the max height information
            if "max_z_height:" in line:
                try:
                    # Extract the max height value after the colon, strip any extra spaces, and convert to float
                    max_height = float(line.split(":")[1].strip())
                    print(
                        f"\nMaximum Z Height: {max_height} mm"
                    )  # Output the max height found
                    return max_height  # Return the max height once found
                except (IndexError, ValueError):
                    # Skip this line if there’s an error in splitting or converting to float
                    continue

        # If no max height information is found, print a message and return the default max_height (0.0)
        print("\nMaximum Z height information not found.")
        return max_height

    # Rest of String Search Functions follow similar format, important pieces commented

    # Search for the length of filmaent used
    def sum_filament_length(self):
        total_filament_length = 0.0
        for line in self.gcode:
            if "total filament length [mm] :" in line:
                try:
                    total_filament_length = float(line.split(":")[1].strip())
                    print(f"\nTotal Filament Length: {total_filament_length} mm")
                    return total_filament_length
                except (IndexError, ValueError):
                    continue
        print("\nTotal filament length information not found.")
        return total_filament_length

    # Search for the weight of filament used
    def sum_filament_weight(self):
        total_filament_weight = 0.0
        for line in self.gcode:
            if "total filament weight [g] :" in line:
                try:
                    total_filament_weight = float(line.split(":")[1].strip())
                    print(f"\nTotal Filament Weight: {total_filament_weight} g")
                    return total_filament_weight
                except (IndexError, ValueError):
                    continue
        print("\nTotal filament weight information not found.")
        return total_filament_weight

    # Find the x width of the object
    def find_x_min_max_difference(self):
        x_min, x_max = float("inf"), float("-inf")
        for line in self.gcode:
            if line.startswith("G1") and " E" in line:
                parts = line.split()
                x_value = None
                for part in parts:
                    if part.startswith("X"):
                        try:
                            x_value = float(part[1:])  # Convert the X value to a float
                        except ValueError:
                            continue

                if x_value is not None:
                    x_min = min(x_min, x_value)
                    x_max = max(x_max, x_value)

        x_difference = x_max - x_min if x_max != float("-inf") else 0
        print(
            f"\nMinimum X: {round(x_min, 2)}, Maximum X: {round(x_max, 2)}, X Difference: {round(x_difference, 2)}"
        )
        return x_min, x_max, x_difference

    # Find the y width of the object
    def find_y_min_max_difference(self):
        y_min, y_max = float("inf"), float("-inf")
        for line in self.gcode:
            if line.startswith("G1") and " E" in line:
                parts = line.split()
                y_value = None
                for part in parts:
                    if part.startswith("Y"):
                        try:
                            y_value = float(part[1:])  # Convert the Y value to a float
                        except ValueError:
                            continue

                if y_value is not None:
                    y_min = min(y_min, y_value)
                    y_max = max(y_max, y_value)

        y_difference = y_max - y_min if y_max != float("-inf") else 0
        print(
            f"\nMinimum Y: {round(y_min, 2)}, Maximum Y: {round(y_max, 2)}, Y Difference: {round(y_difference, 2)}"
        )
        return y_min, y_max, y_difference

    # Find the nozzle temperature
    def find_nozzle_temperature(self):
        nozzle_temp = None
        for line in self.gcode:
            if "; nozzle_temperature =" in line:
                try:
                    nozzle_temp = float(line.split("nozzle_temperature =")[1].strip())
                    print(f"\nNozzle Temperature: {nozzle_temp} \u00b0C")
                    return nozzle_temp
                except (IndexError, ValueError):
                    continue  # Skip lines with incorrect formatting
        if nozzle_temp is None:
            print("\nNo nozzle temperature information found.")
        return nozzle_temp

    # Find the bed temperature
    def find_bed_temperature(self):
        bed_temp = None
        for line in self.gcode:
            if line.startswith("M190 S"):
                try:
                    bed_temp = float(line.split("S")[1].split(";")[0].strip())
                    print(f"\nBed Temperature: {bed_temp} \u00b0C")
                    return bed_temp
                except (IndexError, ValueError):
                    continue  # Skip lines with incorrect formatting
        if bed_temp is None:
            print("\nNo bed temperature information found.")
        return bed_temp

    # Find the model name
    def find_model_name(self):
        if len(self.gcode) > 1:
            model_line = self.gcode[1]
            if "BambuStudio" in model_line:
                model_name = model_line.strip(
                    "; "
                ).strip()  # Remove leading '; ' and extra whitespace
                print(f"\nModel Name: {model_name}")
                return model_name
        print("\nModel name information not found.")
        return None

    # Find the print time
    def find_print_time(self):
        print_time = None
        for line in self.gcode:
            if "total estimated time:" in line:
                try:
                    print_time = line.split(":")[
                        1
                    ].strip()  # Capture the part after 'total estimated time:'
                    print(f"\nEstimated Print Time: {print_time}")
                    return print_time
                except (IndexError, ValueError):
                    continue
        print("\nEstimated print time information not found.")
        return None

    # Using the width and hieght functions find the center in the platform
    def find_build_center(self):
        x_min, x_max, _ = self.find_x_min_max_difference()
        y_min, y_max, _ = self.find_y_min_max_difference()

        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2

        print(
            f"\nCenter Point of Build: X = {round(x_center, 2)}, Y = {round(y_center, 2)}"
        )
        return x_center, y_center

    # For copy and paste straight into the terminal
    def input_from_stdin(self):
        print("Paste your G-code below. Press Enter twice when you're done.")
        gcode = ""
        while True:
            try:
                line = input()
                if line == "":
                    break
                gcode += line + "\n"
            except EOFError:
                break
        self.gcode = gcode.splitlines()
        print("G-code successfully received.")

    # Giving the user options for how to upload the G-Code File
    # Option 1: Enter the file path
    # Option 2: Copy & Paste G-code
    def choose_input_method(self):
        print("Choose how you would like to upload your G-code:")
        print("1. Enter file path to a .gcode file")
        print("2. Copy-paste raw G-code into the terminal")
        method = input("Enter 1 or 2: ")

        if method == "1":
            self.input_from_file()
        elif method == "2":
            self.input_from_stdin()
        else:
            print("Invalid option. Please choose 1 or 2.")
            self.choose_input_method()

    # Define a method to parse extrusion paths from G-code
    def parse_extrusion_paths(self):
        # Initialize an empty list to store parsed paths (positions)
        paths = []
        # Initialize an empty list to store corresponding extrusion values
        e_values = []
        # Set the starting position to the origin (X=0, Y=0, Z=0)
        current_position = [0, 0, 0]
        # Store the last known Z and E (extruder) values to handle lines without Z or E updates
        last_z = 0
        last_e = 0

        # Iterate over each line in the G-code file
        for line in self.gcode:
            # Check if the line is a "G1" command, which represents a linear move in G-code
            if line.startswith("G1"):
                # Search for X, Y, Z, and E values in the current G-code line
                x_match = re.search(r"X([-+]?\d*\.\d+|\d+)", line)
                y_match = re.search(r"Y([-+]?\d*\.\d+|\d+)", line)
                z_match = re.search(r"Z([-+]?\d*\.\d+|\d+)", line)
                e_match = re.search(r"E([-+]?\d*\.\d+|\d+)", line)

                # If an X coordinate is found, update the current X position
                if x_match:
                    current_position[0] = float(x_match.group(1))
                # If a Y coordinate is found, update the current Y position
                if y_match:
                    current_position[1] = float(y_match.group(1))
                # If a Z coordinate is found, update the current Z position and set it as the last Z position
                if z_match:
                    current_position[2] = float(z_match.group(1))
                    last_z = current_position[2]
                else:
                    # If no Z value is found in this line, keep the Z value from the last command
                    current_position[2] = last_z

                # If an E (extruder) value is found, update the current E value
                if e_match:
                    e_value = float(e_match.group(1))
                    last_e = e_value
                else:
                    # If no E value is found, retain the last E value
                    e_value = last_e

                # Append the current position as a tuple to the paths list
                paths.append(tuple(current_position))
                # Append the current E value to the e_values list
                e_values.append(e_value)

        # Return the lists of positions and extruder values
        return paths, e_values

    def generate_lines_from_paths(self, paths):
        # Initialize an empty list to store line segments
        lines = []

        # Iterate over the list of points in 'paths' starting from the second point
        for i in range(1, len(paths)):
            # Define the starting point of the line segment (previous path point)
            start = np.array(paths[i - 1])

            # Define the ending point of the line segment (current path point)
            end = np.array(paths[i])

            # Add the line segment (start, end) as a tuple to the list 'lines'
            lines.append((start, end))

        # Return the list of line segments connecting the path points
        return lines

    def plot_3d_paths(self, lines, e_values):
        fig = plt.figure()
        ax = fig.add_subplot(111, projection="3d")

        # Set up color map for extrusion paths
        norm = plt.Normalize(vmin=min(e_values), vmax=max(e_values))
        cmap = plt.get_cmap("coolwarm")

        max_z = max([p[2] for line in lines for p in line])

        # Create a slider for controlling the Z value
        ax_slider = plt.axes([0.25, 0.02, 0.65, 0.03], facecolor="lightgoldenrodyellow")
        slider = Slider(ax_slider, "Z-Height", 0, max_z, valinit=max_z)

        # Define the update function to handle slider changes
        def update_plot(val):
            ax.cla()  # Clear the current plot

            # Get the Z value from the slider
            z_value = slider.val

            # Plot paths that are "below" or equal to the current slider's Z value
            for i, (start, end) in enumerate(lines):
                # We want to show paths up until the selected Z value
                if (
                    max(start[2], end[2]) <= z_value
                ):  # Show paths where max Z is below the slider value
                    e_value = (
                        (e_values[i] + e_values[i + 1]) / 2
                        if i + 1 < len(e_values)
                        else e_values[i]
                    )
                    color = cmap(norm(e_value))
                    ax.plot(
                        [start[0], end[0]],
                        [start[1], end[1]],
                        [start[2], end[2]],
                        color=color,
                    )

            # Set the labels for each axis of the 3D plot
            ax.set_xlabel("X")
            ax.set_ylabel("Y")
            ax.set_zlabel("Z")

            # Calculate the maximum range of points in the 3D plot for uniform scaling
            # 1. Compute the point-to-point range (ptp) for each axis
            # 2. Create a list comprehension to find the maximum values across each dimension (X, Y, Z)
            # 3. Divide by 2.0 to get half of the range, used for setting plot limits
            max_range = (
                np.ptp(
                    [
                        max([p[i] for start, end in lines for p in (start, end)])
                        for i in range(3)
                    ]
                )
                / 2.0
            )

            # Compute the midpoint of each axis range to center the plot
            mid_x = (ax.get_xlim3d()[0] + ax.get_xlim3d()[1]) * 0.5  # X-axis midpoint
            mid_y = (ax.get_ylim3d()[0] + ax.get_ylim3d()[1]) * 0.5  # Y-axis midpoint
            mid_z = (ax.get_zlim3d()[0] + ax.get_zlim3d()[1]) * 0.5  # Z-axis midpoint

            # Set new limits on each axis, centering the plot at midpoints and using the maximum range
            ax.set_xlim3d([mid_x - max_range, mid_x + max_range])  # Set X-axis limits
            ax.set_ylim3d([mid_y - max_range, mid_y + max_range])  # Set Y-axis limits
            ax.set_zlim3d([mid_z - max_range, mid_z + max_range])  # Set Z-axis limits

            # Redraw the figure to update the plot with the new limits and labels
            plt.draw()

        # Bind the slider to call the `update_plot` function whenever its value changes
        slider.on_changed(update_plot)

        # Initialize the plot by calling `update_plot` with the maximum Z value
        update_plot(max_z)

        # Display the plot with the adjusted settings
        plt.show()

    # Count the number of layers in the G-code file
    def count_layers(self):
        # Initialize layer count to zero
        layer_count = 0
        # Iterate through each line in the G-code
        for line in self.gcode:
            # Check if the line contains the phrase "total layer number:"
            if "total layer number:" in line:
                try:
                    # Split the line at ":" and get the part after it, then convert to integer
                    layer_count = int(line.split(":")[1].strip())
                    # Print the total layer count found in the G-code
                    print(f"\nTotal Layer Count: {layer_count}")
                    # Return the found layer count
                    return layer_count
                except (IndexError, ValueError):
                    # If there's an error in accessing or converting the layer count, skip to the next line
                    continue
        # If no layer count information is found, print a message
        print("\nLayer count information not found.")
        # Return 0 if the layer count was not found in the G-code
        return layer_count

    def export_to_stl(self, paths):
        # Extrude the paths with a small width to create a solid object
        vertices = []
        faces = []

        extrusion_width = 3  # Width/thickness of each path segment
        extrusion_height = 3  # Height of each layer

        for i in range(1, len(paths)):
            start = np.array(paths[i - 1])
            end = np.array(paths[i])

            # Create a rectangular cross-section for each path segment
            offset = np.array([extrusion_width, 0, 0])
            top_start = start + offset + [0, 0, extrusion_height]
            top_end = end + offset + [0, 0, extrusion_height]
            bottom_start = start - offset
            bottom_end = end - offset

            # Define the 8 vertices of a cuboid segment
            vertices.extend([bottom_start, bottom_end, top_end, top_start])

            # Index of the first vertex of this cuboid
            base_idx = len(vertices) - 4

            # Define faces for the cuboid
            faces.append(
                [base_idx, base_idx + 1, base_idx + 2]
            )  # Bottom face triangle 1
            faces.append(
                [base_idx, base_idx + 2, base_idx + 3]
            )  # Bottom face triangle 2
            faces.append([base_idx, base_idx + 3, base_idx + 2])  # Side face triangle 1
            faces.append([base_idx, base_idx + 2, base_idx + 1])  # Side face triangle 2
            faces.append([base_idx, base_idx + 1, base_idx + 2])  # Top face triangle 1
            faces.append([base_idx, base_idx + 2, base_idx + 3])  # Top face triangle 2

        # Convert lists to numpy arrays
        vertices = np.array(vertices)
        faces = np.array(faces)

        # Create the mesh
        model = mesh.Mesh(np.zeros(len(faces), dtype=mesh.Mesh.dtype))
        for i, face in enumerate(faces):
            for j in range(3):
                model.vectors[i][j] = vertices[face[j], :]

        # Save the STL file
        model.save("output_model.stl")
        print("STL file has been saved as output_model.stl")


def main():
    processor = GcodeProcessor()
    processor.choose_input_method()

    if processor.gcode is None:
        print("No G-code to process.")
        return

    # Run all string search functions
    processor.count_layers()
    processor.sum_layer_heights()
    processor.sum_filament_length()
    processor.sum_filament_weight()
    processor.find_x_min_max_difference()
    processor.find_y_min_max_difference()
    processor.find_nozzle_temperature()
    processor.find_bed_temperature()
    processor.find_model_name()
    processor.find_print_time()
    processor.find_build_center()

    # Run the parsing
    paths, e_values = processor.parse_extrusion_paths()
    lines = processor.generate_lines_from_paths(paths)

    # Plot the extrusion paths
    # processor.plot_3d_paths(lines, e_values)

    # Export the paths to an STL file
    processor.export_to_stl(paths)


if __name__ == "__main__":
    main()

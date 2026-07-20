import { Scene } from "@xeokit/sdk/scene";
import { Data, searchObjects } from "@xeokit/sdk/data";
import { Viewer } from "@xeokit/sdk/viewer";
import { WebGLRenderer } from "@xeokit/sdk/webglrenderer";
import { ViewController } from "@xeokit/sdk/cameracontrol";
import { IFCLoader } from "@xeokit/sdk/formats/dotbim";

// Create containers for geometry and optional structural data

const scene = new Scene();
const data = new Data();

// Create a Viewer and WebGL renderer

const viewer = new Viewer({ scene });
new WebGLRenderer({ viewer });

// Create a View bound to an existing canvas element

const view = viewer.createView({
  id: "myView",
  elementId: "myCanvas", // Ensure this element exists
}).value;

// Position the camera

view.camera.eye = [-6.01, 4.85, 9.11];
view.camera.look = [3.93, -2.65, -12.51];
view.camera.up = [0.12, 0.95, -0.27];

// Enable mouse / touch camera interaction

new ViewController(view, {});

// Create target models for the loader

const sceneModel = scene.createModel({ id: "myModel" }).value;
const dataModel = data.createModel({ id: "myModel" }).value;

// Create the IFC loader

const ifcLoader = new IFCLoader();

// Fetch and decode the IFC file

fetch("model.ifc")
  .then((r) => r.arrayBuffer())
  .then((fileData) => {
    // Load geometry (and optional node hierarchy) into the models

    return ifcLoader.load({
      fileData,
      sceneModel,
      dataModel,
    });
  })
  .then(() => {
    // Model successfully loaded and visible.

    // Search the data graph for IfcWall objects, starting at the
    // IfcProject root node, including any children via IfcRelAggregates relationships.

    const resultObjectIds = [];

    const result = searchObjects(data, {
      startObjectId: "38aOKO8_DDkBd1FHm_lVXz", // Root IfcProject ID
      includeObjects: ["IfcWall"],
      includeRelated: ["IfcRelAggregates"],
      resultObjectIds,
    });

    // Check if the query succeeded.

    if (!result.ok) {
      console.error("Error querying IFC data: " + result.error);
      return;
    }

    // If the query succeeded, go ahead and mark whatever
    // objects we found as selected. Now all the IfcWall objects
    // in the Viewer will appear selected and glowing.

    view.setObjectsSelected(resultObjectIds, true);
  })
  .catch((err) => {
    // Clean up on failure
    sceneModel.destroy();
    dataModel.destroy();
    console.error("Error loading IFC:", err);
  });

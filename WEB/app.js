import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  CSS2DRenderer,
  CSS2DObject,
} from "three/addons/renderers/CSS2DRenderer.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { FXAAShader } from "three/addons/shaders/FXAAShader.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";

// ========== Система логирования ==========
const Logger = {
  logElement: null,

  init() {
    this.logElement = document.getElementById("log-content");
    if (!this.logElement) {
      console.log("Ожидание создания log-content...");
      return false;
    }
    return true;
  },

  add(message, type = "info") {
    if (!this.logElement) {
      console.log(`[${type}] ${message}`);
      return;
    }

    const entry = document.createElement("div");
    entry.className = `log-entry log-${type}`;
    const time = new Date().toLocaleTimeString();
    entry.innerHTML = `<span style="color:#888">[${time}]</span> ${message}`;
    this.logElement.appendChild(entry);
    entry.scrollIntoView({ behavior: "smooth", block: "nearest" });

    const consoleMethod =
      type === "error" ? "error" : type === "warning" ? "warn" : "log";
    console[consoleMethod](message);
  },

  clear() {
    if (this.logElement) {
      this.logElement.innerHTML = "";
      this.add("Лог очищен", "info");
    }
  },

  info(message) {
    this.add(message, "info");
  },
  success(message) {
    this.add(message, "success");
  },
  error(message) {
    this.add(message, "error");
  },
  warning(message) {
    this.add(message, "warning");
  },
};

// ========== Основные переменные ==========
let scene, camera, renderer, labelRenderer, controls;
let effectComposer = null;
let mainGroup;
let currentModel = null;
let pointsCount = 0;
let segmentsCount = 0;
let totalFilament = 0;

// Источники света (3 источника)
let ambientLight;
let light1, light2, light3;
let lightSpheres = []; // Сферы для визуализации источников света

// Состояние измерения
let measuringMode = false;
let measurePoints = [];
let measureObjects = [];

// Состояние сечения
let sectionPlane = null;
let isClipped = false;

// UI элементы
let statsElement, coordsElement;
let lastTime = performance.now();
let frameCount = 0;

// ========== Инициализация ==========
async function init() {
  try {
    console.log("Начало инициализации...");

    await new Promise((resolve) => setTimeout(resolve, 100));

    Logger.init();
    Logger.info("Инициализация 3D сцены...");

    statsElement = document.getElementById("stats");
    coordsElement = document.getElementById("coords");

    // Сцена
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1a1a2e);

    // Камера
    camera = new THREE.PerspectiveCamera(
      45,
      window.innerWidth / window.innerHeight,
      0.1,
      20000,
    );
    camera.position.set(800, 600, 1000);
    camera.lookAt(0, 0, 0);

    // Рендерер
    renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
    });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(window.devicePixelRatio);
    document.body.appendChild(renderer.domElement);

    // CSS2 рендерер для текста
    labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(window.innerWidth, window.innerHeight);
    labelRenderer.domElement.style.position = "absolute";
    labelRenderer.domElement.style.top = "0px";
    labelRenderer.domElement.style.left = "0px";
    labelRenderer.domElement.style.pointerEvents = "none";
    document.body.appendChild(labelRenderer.domElement);

    // Управление
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.rotateSpeed = 1.5;
    controls.zoomSpeed = 1.2;
    controls.panSpeed = 0.8;

    // Группа для модели
    mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // Вспомогательные элементы
    setupLights();
    addLightSpheres();
    addGridHelper();
    addAxesHelper();

    // Настройка эффектов
    setupEffectComposer();

    // Запуск анимации
    animate();

    // Настройка UI после загрузки
    setupUI();

    window.addEventListener("resize", onWindowResize);
    setupMeasurementClick();

    Logger.success("Приложение успешно инициализировано");

    if (statsElement) {
      statsElement.innerHTML = "⚡ Готов к работе | Ожидание файла";
    }
  } catch (err) {
    console.error("Ошибка инициализации:", err);
    Logger.error(`Ошибка инициализации: ${err.message}`);
  }
}

// ========== Настройка Effect Composer для AA ==========
function setupEffectComposer() {
  effectComposer = new EffectComposer(renderer);
  const renderPass = new RenderPass(scene, camera);
  effectComposer.addPass(renderPass);
}

function setAntiAliasing(level) {
  if (!effectComposer) return;

  while (effectComposer.passes.length > 1) {
    effectComposer.removePass(effectComposer.passes[1]);
  }

  if (level === "off") {
    Logger.info("Anti-aliasing выключен");
    return;
  }

  const fxaaPass = new ShaderPass(FXAAShader);
  const pixelRatio = renderer.getPixelRatio();
  fxaaPass.uniforms["resolution"].value.x =
    1 / (window.innerWidth * pixelRatio);
  fxaaPass.uniforms["resolution"].value.y =
    1 / (window.innerHeight * pixelRatio);
  effectComposer.addPass(fxaaPass);
  fxaaPass.renderToScreen = true;

  Logger.info(`Anti-aliasing включен: ${level}x`);
}

// ========== Добавление сфер для визуализации источников света ==========
function addLightSpheres() {
  // Удаляем старые сферы
  lightSpheres.forEach((sphere) => scene.remove(sphere));
  lightSpheres = [];

  // Создаем сферы для каждого источника света
  const sphereGeometry = new THREE.SphereGeometry(20, 16, 16);

  // Сфера для света 1 (оранжевая)
  const sphere1 = new THREE.Mesh(
    sphereGeometry,
    new THREE.MeshStandardMaterial({
      color: 0xffaa66,
      emissive: 0x442200,
      emissiveIntensity: 0.5,
    }),
  );
  scene.add(sphere1);
  lightSpheres.push(sphere1);

  // Сфера для света 2 (белая)
  const sphere2 = new THREE.Mesh(
    sphereGeometry,
    new THREE.MeshStandardMaterial({
      color: 0xffffff,
      emissive: 0x222222,
      emissiveIntensity: 0.3,
    }),
  );
  scene.add(sphere2);
  lightSpheres.push(sphere2);

  // Сфера для света 3 (голубая)
  const sphere3 = new THREE.Mesh(
    sphereGeometry,
    new THREE.MeshStandardMaterial({
      color: 0x88aaff,
      emissive: 0x002244,
      emissiveIntensity: 0.4,
    }),
  );
  scene.add(sphere3);
  lightSpheres.push(sphere3);

  // Обновляем позиции сфер
  updateLightSpheresPositions();
}

function updateLightSpheresPositions() {
  if (!light1) return;

  const pos1 = light1.position;
  const pos2 = light2.position;
  const pos3 = light3.position;

  if (lightSpheres[0]) lightSpheres[0].position.copy(pos1);
  if (lightSpheres[1]) lightSpheres[1].position.copy(pos2);
  if (lightSpheres[2]) lightSpheres[2].position.copy(pos3);
}

// ========== Настройка освещения ==========
function setupLights() {
  // Ambient свет
  ambientLight = new THREE.AmbientLight(0x888888, 0.6);
  scene.add(ambientLight);

  // Свет 1: сверху 4000мм и справа 500мм (X=500, Y=4000, Z=0)
  light1 = new THREE.DirectionalLight(0xffaa88, 0.7);
  light1.position.set(500, 4000, 0);
  scene.add(light1);

  // Свет 2: сверху 3000мм и по X и Z на 1000мм
  light2 = new THREE.DirectionalLight(0xffffff, 0.6);
  light2.position.set(1000, 3000, 1000);
  scene.add(light2);

  // Свет 3: сверху 3000мм и по X и Z на -1000мм
  light3 = new THREE.DirectionalLight(0x88aaff, 0.5);
  light3.position.set(-1000, 3000, -1000);
  scene.add(light3);
}

// ========== Обновление освещения ==========
function updateLights() {
  const ambientInt = parseFloat(
    document.getElementById("ambient-intensity")?.value || 0.6,
  );

  // Свет 1
  const light1Height = parseFloat(
    document.getElementById("light1-height")?.value || 4000,
  );
  const light1X = parseFloat(document.getElementById("light1-x")?.value || 500);
  const light1Int = parseFloat(
    document.getElementById("light1-intensity")?.value || 0.7,
  );

  // Свет 2
  const light2Height = parseFloat(
    document.getElementById("light2-height")?.value || 3000,
  );
  const light2X = parseFloat(
    document.getElementById("light2-x")?.value || 1000,
  );
  const light2Z = parseFloat(
    document.getElementById("light2-z")?.value || 1000,
  );
  const light2Int = parseFloat(
    document.getElementById("light2-intensity")?.value || 0.6,
  );

  // Свет 3
  const light3Height = parseFloat(
    document.getElementById("light3-height")?.value || 3000,
  );
  const light3X = parseFloat(
    document.getElementById("light3-x")?.value || -1000,
  );
  const light3Z = parseFloat(
    document.getElementById("light3-z")?.value || -1000,
  );
  const light3Int = parseFloat(
    document.getElementById("light3-intensity")?.value || 0.5,
  );

  if (ambientLight) ambientLight.intensity = ambientInt;
  if (light1) {
    light1.position.set(light1X, light1Height, 0);
    light1.intensity = light1Int;
  }
  if (light2) {
    light2.position.set(light2X, light2Height, light2Z);
    light2.intensity = light2Int;
  }
  if (light3) {
    light3.position.set(light3X, light3Height, light3Z);
    light3.intensity = light3Int;
  }

  // Обновляем позиции сфер-визуализаторов
  updateLightSpheresPositions();

  Logger.info("Освещение обновлено");
}

// ========== Вспомогательные элементы ==========
function addGridHelper() {
  const gridHelper = new THREE.GridHelper(3000, 30, 0x888888, 0x444444);
  gridHelper.position.y = -0.1;
  gridHelper.material.transparent = true;
  gridHelper.material.opacity = 0.3;
  scene.add(gridHelper);
}

function addAxesHelper() {
  const axesHelper = new THREE.AxesHelper(800);
  axesHelper.material.transparent = true;
  axesHelper.material.opacity = 0.2;
  scene.add(axesHelper);

  const makeAxisLabel = (text, color, position) => {
    const div = document.createElement("div");
    div.textContent = text;
    div.style.color = color;
    div.style.fontSize = "14px";
    div.style.fontWeight = "bold";
    div.style.textShadow = "1px 1px 0px black";
    const label = new CSS2DObject(div);
    label.position.copy(position);
    scene.add(label);
  };

  makeAxisLabel("X", "#ff8888", new THREE.Vector3(850, 0, 0));
  makeAxisLabel("Y", "#88ff88", new THREE.Vector3(0, 850, 0));
  makeAxisLabel("Z", "#8888ff", new THREE.Vector3(0, 0, 850));
}

// ========== Создание толстой линии с матовым материалом ==========
// Диаметр трубки напрямую соответствует значению ползунка (1-10 мм)
function createThickLine(points, color, diameter) {
  if (points.length < 2) return null;

  try {
    const curve = new THREE.CatmullRomCurve3(points);
    const tubularSegments = Math.max(20, Math.floor(points.length * 1.2));
    const radialSegments = 12; // Больше сегментов для гладкости при большом диаметре

    // Радиус = половина диаметра
    const radius = diameter / 2;

    const geometry = new THREE.TubeGeometry(
      curve,
      tubularSegments,
      radius,
      radialSegments,
      false,
    );

    // Матовый материал - керамика/цемент
    const material = new THREE.MeshStandardMaterial({
      color: color,
      roughness: 0.92,
      metalness: 0.02,
      emissive: 0x222222,
      emissiveIntensity: 0.05,
      flatShading: false,
    });

    const tube = new THREE.Mesh(geometry, material);
    tube.castShadow = false;
    tube.receiveShadow = false;

    return tube;
  } catch (err) {
    console.warn("Ошибка создания трубки:", err);
    return null;
  }
}

// ========== Создание модели из сегментов ==========
function createModelFromSegments1(segments, color, diameter) {
  const group = new THREE.Group();
  let tubeCount = 0;

  for (const segment of segments) {
    if (segment.length < 2) continue;

    const points = segment.map((p) => new THREE.Vector3(p.x, p.z, p.y));
    const maxPointsPerTube = 200;

    if (points.length <= maxPointsPerTube) {
      const tube = createThickLine(points, color, diameter);
      if (tube) {
        group.add(tube);
        tubeCount++;
      }
    } else {
      for (let i = 0; i < points.length - 1; i += maxPointsPerTube - 1) {
        const chunk = points.slice(
          i,
          Math.min(i + maxPointsPerTube, points.length),
        );
        if (chunk.length >= 2) {
          const tube = createThickLine(chunk, color, diameter);
          if (tube) {
            group.add(tube);
            tubeCount++;
          }
        }
      }
    }
  }

  Logger.info(`Создано трубок: ${tubeCount}, диаметр: ${diameter} мм`);
  return group;
}

// ========== Создание модели из сегментов (непрерывная труба) ==========
function createModelFromSegments(segments, color, diameter) {
  const group = new THREE.Group();

  // Собираем ВСЕ точки в один непрерывный массив
  const allPoints = [];

  for (const segment of segments) {
    if (segment.length === 0) continue;

    // Добавляем точки сегмента
    for (const pt of segment) {
      allPoints.push(new THREE.Vector3(pt.x, pt.z, pt.y));
    }
  }

  if (allPoints.length < 2) {
    Logger.warning("Недостаточно точек для создания модели");
    return group;
  }

  Logger.info(`Создание непрерывной трубы из ${allPoints.length} точек...`);

  // Создаем ОДНУ непрерывную кривую через все точки
  const curve = new THREE.CatmullRomCurve3(allPoints);

  // Параметры трубки
  const tubularSegments = Math.max(100, Math.floor(allPoints.length));
  const radialSegments = 12;
  const radius = diameter / 2;

  const geometry = new THREE.TubeGeometry(
    curve,
    tubularSegments,
    radius,
    radialSegments,
    false,
  );

  // Матовый материал
  const material = new THREE.MeshStandardMaterial({
    color: color,
    roughness: 0.92,
    metalness: 0.02,
    emissive: 0x222222,
    emissiveIntensity: 0.05,
  });

  const tube = new THREE.Mesh(geometry, material);
  tube.castShadow = false;
  tube.receiveShadow = false;
  group.add(tube);

  Logger.info(`Создана непрерывная труба, диаметр: ${diameter} мм`);
  return group;
}

// ========== Парсинг G-code ==========
class GCodeParser {
  constructor() {
    this.points = [];
    this.segments = [];
    this.totalE = 0;
  }

  parse(content) {
    this.points = [];
    this.segments = [];
    this.totalE = 0;

    const lines = content.split("\n");
    let currentPos = { x: 0, y: 0, z: 0 };
    let currentPath = [{ ...currentPos }];

    for (const line of lines) {
      if (
        !line.trim() ||
        line.startsWith(";") ||
        line.startsWith("(") ||
        line.startsWith("%")
      ) {
        continue;
      }

      const parts = line.trim().split(/\s+/);
      let isG1 = false;
      let newPos = { ...currentPos };
      let hasMove = false;

      for (const part of parts) {
        if (part === "G1" || part === "G01") {
          isG1 = true;
        } else if (part.startsWith("X")) {
          newPos.x = parseFloat(part.substring(1));
          hasMove = true;
        } else if (part.startsWith("Y")) {
          newPos.y = parseFloat(part.substring(1));
          hasMove = true;
        } else if (part.startsWith("Z")) {
          newPos.z = parseFloat(part.substring(1));
          hasMove = true;
        } else if (part.startsWith("E")) {
          const e = parseFloat(part.substring(1));
          if (e > 0) this.totalE += e;
        }
      }

      if (isG1 && hasMove) {
        if (
          currentPath[currentPath.length - 1].x !== newPos.x ||
          currentPath[currentPath.length - 1].y !== newPos.y ||
          currentPath[currentPath.length - 1].z !== newPos.z
        ) {
          currentPath.push(newPos);
        }
        currentPos = newPos;
      } else if (hasMove) {
        if (currentPath.length > 1) {
          this.segments.push([...currentPath]);
        }
        currentPath = [{ ...newPos }];
        currentPos = newPos;
      }
    }

    if (currentPath.length > 1) {
      this.segments.push([...currentPath]);
    }

    for (const seg of this.segments) {
      for (const pt of seg) {
        this.points.push(pt);
      }
    }

    Logger.info(
      `Парсинг завершен. Сегментов: ${this.segments.length}, точек: ${this.points.length}`,
    );
    Logger.info(`Общий расход филамента: ${this.totalE.toFixed(2)} мм`);
    return this.segments.length > 0;
  }

  getBounds() {
    if (this.points.length === 0)
      return { min: { x: 0, y: 0, z: 0 }, max: { x: 100, y: 100, z: 100 } };

    let minX = Infinity,
      minY = Infinity,
      minZ = Infinity;
    let maxX = -Infinity,
      maxY = -Infinity,
      maxZ = -Infinity;

    for (const pt of this.points) {
      minX = Math.min(minX, pt.x);
      minY = Math.min(minY, pt.y);
      maxX = Math.max(maxX, pt.x);
      maxY = Math.max(maxY, pt.y);
      minZ = Math.min(minZ, pt.z);
      maxZ = Math.max(maxZ, pt.z);
    }

    return {
      min: { x: minX, y: minY, z: minZ },
      max: { x: maxX, y: maxY, z: maxZ },
    };
  }
}

// ========== Загрузка файла ==========
async function loadGCode(file) {
  const statusDiv = document.getElementById("file-status");
  const progressBar = document.getElementById("progress-bar");
  const progressFill = document.getElementById("progress-fill");

  if (!statusDiv) return;

  statusDiv.innerHTML = "⏳ Загрузка файла...";
  statusDiv.style.color = "#ff9800";
  if (progressBar) progressBar.style.display = "block";
  if (progressFill) progressFill.style.width = "30%";

  Logger.info(`Загрузка: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`);

  try {
    const content = await file.text();
    if (progressFill) progressFill.style.width = "60%";

    const parser = new GCodeParser();
    statusDiv.innerHTML = "⏳ Парсинг G-code...";

    if (parser.parse(content)) {
      if (progressFill) progressFill.style.width = "80%";

      const bounds = parser.getBounds();
      const segments = parser.segments;
      totalFilament = parser.totalE;

      // Размеры модели
      const sizeX = (bounds.max.x - bounds.min.x).toFixed(1);
      const sizeY = (bounds.max.y - bounds.min.y).toFixed(1);
      const sizeZ = (bounds.max.z - bounds.min.z).toFixed(1);

      const dimElement = document.getElementById("model-dimensions");
      const statsInfoElement = document.getElementById("model-stats");

      if (dimElement) {
        dimElement.innerHTML = `
                    <span>📏 Длина (X):</span> ${sizeX} мм<br>
                    <span>📐 Ширина (Y):</span> ${sizeY} мм<br>
                    <span>📏 Высота (Z):</span> ${sizeZ} мм
                `;
        Logger.info(`Размеры модели: X=${sizeX}, Y=${sizeY}, Z=${sizeZ}`);
      }
      if (statsInfoElement) {
        statsInfoElement.innerHTML = `
                    <span>🔘 Точек:</span> ${parser.points.length.toLocaleString()}<br>
                    <span>🧵 Филамента:</span> ${totalFilament.toFixed(2)} мм
                `;
        Logger.info(
          `Статистика: точек=${parser.points.length}, филамента=${totalFilament.toFixed(2)} мм`,
        );
      }

      // НОВОЕ: центрирование по X и Y, Z привязан к 0
      const centerX = (bounds.min.x + bounds.max.x) / 2;
      const centerY = (bounds.min.y + bounds.max.y) / 2;
      const minZ = bounds.min.z; // Находим самую нижнюю точку по Z

      for (const seg of segments) {
        for (const pt of seg) {
          pt.x -= centerX;
          pt.y -= centerY;
          pt.z -= minZ; // Смещаем так, чтобы нижняя точка стала Z=0
        }
      }

      if (currentModel) {
        mainGroup.remove(currentModel);
      }

      const color = document.getElementById("color-picker")?.value || "#c4a882";
      const diameter = parseFloat(
        document.getElementById("thickness-slider")?.value || "3",
      );

      statusDiv.innerHTML = "⏳ Создание 3D модели...";
      Logger.info(`Создание модели (диаметр: ${diameter} мм)...`);

      currentModel = createModelFromSegments(segments, color, diameter);
      currentModel.userData = {
        bounds: bounds,
        segments: segments,
        diameter: diameter,
      };

      mainGroup.add(currentModel);
      pointsCount = parser.points.length;
      segmentsCount = segments.length;

      if (progressFill) progressFill.style.width = "100%";
      statusDiv.innerHTML = `✅ Загружено: ${pointsCount.toLocaleString()} точек, ${segmentsCount} сегментов`;
      statusDiv.style.color = "#4caf50";

      Logger.success(
        `Модель создана! Точек: ${pointsCount}, объектов: ${currentModel.children.length}`,
      );

      // Настройка камеры
      const maxDim = Math.max(
        bounds.max.x - bounds.min.x,
        bounds.max.y - bounds.min.y,
        bounds.max.z - bounds.min.z,
      );
      const distance = Math.max(maxDim * 1.5, 500);
      camera.position.set(distance * 0.8, distance * 0.6, distance);
      controls.target.set(0, 0, 0);
      controls.update();
    } else {
      statusDiv.innerHTML = "❌ Ошибка: Не удалось распарсить G-code";
      Logger.error("Ошибка парсинга G-code");
    }

    setTimeout(() => {
      if (progressBar) progressBar.style.display = "none";
      if (progressFill) progressFill.style.width = "0%";
    }, 1000);
  } catch (err) {
    statusDiv.innerHTML = `❌ Ошибка: ${err.message}`;
    Logger.error(`Ошибка: ${err.message}`);
    if (progressBar) progressBar.style.display = "none";
  }
}

// ========== Обновление внешнего вида ==========
function updateModelAppearance() {
  if (!currentModel) return;

  const color = document.getElementById("color-picker")?.value || "#c4a882";
  const newDiameter = parseFloat(
    document.getElementById("thickness-slider")?.value || "3",
  );
  const opacity =
    parseInt(document.getElementById("opacity-slider")?.value || "100") / 100;

  const currentDiameter = currentModel.userData?.diameter || newDiameter;

  if (Math.abs(currentDiameter - newDiameter) > 0.1) {
    regenerateModel(newDiameter, color, opacity);
  } else {
    currentModel.children.forEach((child) => {
      if (child.isMesh) {
        child.material.color.set(color);
        child.material.opacity = opacity;
        child.material.transparent = opacity < 1;
      }
    });
  }
}

function regenerateModel(diameter, color, opacity) {
  if (
    !currentModel ||
    !currentModel.userData ||
    !currentModel.userData.segments
  ) {
    Logger.warning("Нет данных для пересоздания модели");
    return;
  }

  const segments = currentModel.userData.segments;
  const statusDiv = document.getElementById("file-status");
  const originalText = statusDiv?.innerHTML;

  if (statusDiv) {
    statusDiv.innerHTML = "⏳ Обновление диаметра трубок...";
    statusDiv.style.color = "#ff9800";
  }

  setTimeout(() => {
    try {
      const newModel = createModelFromSegments(segments, color, diameter);
      newModel.userData = {
        ...currentModel.userData,
        diameter: diameter,
      };

      newModel.children.forEach((child) => {
        if (child.isMesh) {
          child.material.opacity = opacity;
          child.material.transparent = opacity < 1;
        }
      });

      mainGroup.remove(currentModel);
      currentModel = newModel;
      mainGroup.add(currentModel);

      if (isClipped && sectionPlane) {
        // applyClipping('right');
      }

      Logger.success(`Модель обновлена: диаметр ${diameter} мм`);

      if (statusDiv) {
        statusDiv.innerHTML = originalText || "Готово";
        statusDiv.style.color = "#4caf50";
      }
    } catch (err) {
      Logger.error(`Ошибка обновления модели: ${err.message}`);
    }
  }, 10);
}

// ========== Обновление отображения значений слайдеров ==========
function updateSliderValues() {
  // Ambient
  const ambient = document.getElementById("ambient-intensity");
  if (ambient)
    document.getElementById("ambient-value").textContent = parseFloat(
      ambient.value,
    ).toFixed(2);

  // Свет 1
  const l1h = document.getElementById("light1-height");
  if (l1h)
    document.getElementById("light1-height-value").textContent = l1h.value;
  const l1x = document.getElementById("light1-x");
  if (l1x) document.getElementById("light1-x-value").textContent = l1x.value;
  const l1i = document.getElementById("light1-intensity");
  if (l1i)
    document.getElementById("light1-int-value").textContent = parseFloat(
      l1i.value,
    ).toFixed(2);

  // Свет 2
  const l2h = document.getElementById("light2-height");
  if (l2h)
    document.getElementById("light2-height-value").textContent = l2h.value;
  const l2x = document.getElementById("light2-x");
  if (l2x) document.getElementById("light2-x-value").textContent = l2x.value;
  const l2z = document.getElementById("light2-z");
  if (l2z) document.getElementById("light2-z-value").textContent = l2z.value;
  const l2i = document.getElementById("light2-intensity");
  if (l2i)
    document.getElementById("light2-int-value").textContent = parseFloat(
      l2i.value,
    ).toFixed(2);

  // Свет 3
  const l3h = document.getElementById("light3-height");
  if (l3h)
    document.getElementById("light3-height-value").textContent = l3h.value;
  const l3x = document.getElementById("light3-x");
  if (l3x) document.getElementById("light3-x-value").textContent = l3x.value;
  const l3z = document.getElementById("light3-z");
  if (l3z) document.getElementById("light3-z-value").textContent = l3z.value;
  const l3i = document.getElementById("light3-intensity");
  if (l3i)
    document.getElementById("light3-int-value").textContent = parseFloat(
      l3i.value,
    ).toFixed(2);
}

// ========== Настройка UI ==========
function setupUI() {
  // Файл
  const fileInput = document.getElementById("file-input");
  if (fileInput) {
    fileInput.addEventListener("change", (e) => {
      if (e.target.files.length > 0) {
        loadGCode(e.target.files[0]);
      }
    });
  }

  // Внешний вид
  const thicknessSlider = document.getElementById("thickness-slider");
  if (thicknessSlider) {
    thicknessSlider.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value);
      const display = document.getElementById("thickness-value");
      if (display) display.textContent = val.toFixed(1);
      updateModelAppearance();
    });
  }

  const colorPicker = document.getElementById("color-picker");
  if (colorPicker) {
    colorPicker.addEventListener("input", () => updateModelAppearance());
  }

  const opacitySlider = document.getElementById("opacity-slider");
  if (opacitySlider) {
    opacitySlider.addEventListener("input", (e) => {
      const display = document.getElementById("opacity-value");
      if (display) display.textContent = e.target.value + "%";
      updateModelAppearance();
    });
  }

  const bgColor = document.getElementById("bg-color");
  if (bgColor) {
    bgColor.addEventListener("input", (e) => {
      scene.background = new THREE.Color(e.target.value);
    });
  }

  // Anti-aliasing
  document
    .getElementById("aa-off")
    ?.addEventListener("click", () => setAntiAliasing("off"));
  document
    .getElementById("aa-2")
    ?.addEventListener("click", () => setAntiAliasing("2x"));
  document
    .getElementById("aa-4")
    ?.addEventListener("click", () => setAntiAliasing("4x"));
  document
    .getElementById("aa-8")
    ?.addEventListener("click", () => setAntiAliasing("8x"));

  // Освещение - обновление значений при движении
  const lightSliders = [
    "ambient-intensity",
    "light1-height",
    "light1-x",
    "light1-intensity",
    "light2-height",
    "light2-x",
    "light2-z",
    "light2-intensity",
    "light3-height",
    "light3-x",
    "light3-z",
    "light3-intensity",
  ];

  lightSliders.forEach((id) => {
    const slider = document.getElementById(id);
    if (slider) {
      slider.addEventListener("input", () => updateSliderValues());
    }
  });

  // Кнопка применить освещение
  const applyLightsBtn = document.getElementById("apply-lights-btn");
  if (applyLightsBtn) {
    applyLightsBtn.addEventListener("click", () => {
      updateLights();
      Logger.success("Настройки освещения применены");
    });
  }

  // Камера
  const cameraPositions = {
    "cam-front": [0, 0, 1200],
    "cam-back": [0, 0, -1200],
    "cam-left": [-1200, 0, 0],
    "cam-right": [1200, 0, 0],
    "cam-top": [0, 1200, 0],
    "cam-bottom": [0, -1200, 0],
    "cam-iso": [800, 600, 1000],
    "cam-reset": [800, 600, 1000],
  };

  for (const [id, pos] of Object.entries(cameraPositions)) {
    const btn = document.getElementById(id);
    if (btn) {
      btn.addEventListener("click", () => {
        camera.position.set(pos[0], pos[1], pos[2]);
        controls.target.set(0, 0, 0);
        controls.update();
      });
    }
  }

  // Скриншот
  const screenshotBtn = document.getElementById("screenshot-btn");
  if (screenshotBtn) {
    screenshotBtn.addEventListener("click", () => {
      renderer.render(scene, camera);
      const dataURL = renderer.domElement.toDataURL("image/png");
      const link = document.createElement("a");
      link.href = dataURL;
      link.download = `gcode-screenshot-${Date.now()}.png`;
      link.click();
      Logger.info("Скриншот сохранен");
    });
  }

  // Лог
  const logClear = document.getElementById("log-clear");
  if (logClear) {
    logClear.addEventListener("click", () => Logger.clear());
  }

  // Сворачивание панели
  let panelVisible = true;
  const panel = document.getElementById("ui-panel");
  const toggleBtn = document.getElementById("toggle-panel");
  if (toggleBtn && panel) {
    toggleBtn.addEventListener("click", () => {
      panelVisible = !panelVisible;
      panel.classList.toggle("hidden", !panelVisible);
      toggleBtn.textContent = panelVisible ? "◀" : "▶";
      toggleBtn.style.left = panelVisible ? "320px" : "20px";
    });
  }

  // Сворачивание лога
  let logVisible = true;
  const logPanel = document.getElementById("log-panel");
  const logHeader = document.getElementById("log-header");
  if (logHeader && logPanel) {
    logHeader.addEventListener("click", () => {
      logVisible = !logVisible;
      logPanel.classList.toggle("hidden", !logVisible);
    });
  }

  // Инициализация отображения значений
  updateSliderValues();
}

// ========== Настройка измерений ==========
function setupMeasurementClick() {
  const measureBtn = document.getElementById("measure-btn");
  const resetMeasureBtn = document.getElementById("reset-measure-btn");

  if (measureBtn) {
    measureBtn.addEventListener("click", () => {
      measuringMode = !measuringMode;
      measureBtn.textContent = measuringMode
        ? "🔍 Измерение активно"
        : "🔍 Измерить";
      document.getElementById("measure-result").innerHTML = measuringMode
        ? 'Расстояние: — <span style="color:#ff9800">(щелкните 2 точки)</span>'
        : "Расстояние: —";
      Logger.info(
        measuringMode
          ? "Режим измерения активирован"
          : "Режим измерения деактивирован",
      );
    });
  }

  if (resetMeasureBtn) {
    resetMeasureBtn.addEventListener("click", () => {
      measuringMode = false;
      measurePoints = [];
      measureObjects.forEach((obj) => scene.remove(obj));
      measureObjects = [];
      document.getElementById("measure-result").innerHTML = "Расстояние: —";
      if (measureBtn) measureBtn.textContent = "🔍 Измерить";
      Logger.info("Измерения сброшены");
    });
  }

  renderer.domElement.addEventListener("click", (event) => {
    if (!measuringMode || !currentModel) return;

    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();

    mouse.x = (event.clientX / renderer.domElement.clientWidth) * 2 - 1;
    mouse.y = -(event.clientY / renderer.domElement.clientHeight) * 2 + 1;

    raycaster.setFromCamera(mouse, camera);
    const intersects = raycaster.intersectObjects(currentModel.children, true);

    if (intersects.length > 0) {
      const point = intersects[0].point;

      const geometry = new THREE.SphereGeometry(5, 8, 8);
      const material = new THREE.MeshStandardMaterial({ color: 0xff4444 });
      const sphere = new THREE.Mesh(geometry, material);
      sphere.position.copy(point);
      scene.add(sphere);
      measureObjects.push(sphere);

      measurePoints.push(point.clone());

      if (measurePoints.length === 2) {
        const dist = measurePoints[0].distanceTo(measurePoints[1]);
        document.getElementById("measure-result").innerHTML =
          `📏 Расстояние: ${dist.toFixed(2)} мм`;
        Logger.info(`Расстояние: ${dist.toFixed(2)} мм`);

        const points = [measurePoints[0], measurePoints[1]];
        const lineGeo = new THREE.BufferGeometry().setFromPoints(points);
        const lineMat = new THREE.LineBasicMaterial({ color: 0x44ff44 });
        const line = new THREE.Line(lineGeo, lineMat);
        scene.add(line);
        measureObjects.push(line);

        measuringMode = false;
        if (measureBtn) measureBtn.textContent = "🔍 Измерить";
      }
    }
  });
}

// ========== Анимация ==========
function animate() {
  requestAnimationFrame(animate);
  controls.update();

  if (effectComposer && effectComposer.passes.length > 1) {
    effectComposer.render();
  } else {
    renderer.render(scene, camera);
  }
  labelRenderer.render(scene, camera);

  frameCount++;
  const now = performance.now();
  if (now - lastTime >= 1000) {
    const fps = Math.round((frameCount * 1000) / (now - lastTime));
    if (statsElement) {
      statsElement.innerHTML = `⚡ ${fps} FPS | 📍 ${pointsCount.toLocaleString()} точек | 🔘 ${currentModel ? currentModel.children.length : 0} объектов`;
    }
    frameCount = 0;
    lastTime = now;
  }
}

function onWindowResize() {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  labelRenderer.setSize(window.innerWidth, window.innerHeight);
  if (effectComposer) {
    effectComposer.setSize(window.innerWidth, window.innerHeight);
  }
}

// Запуск
window.addEventListener("load", () => {
  console.log("Страница полностью загружена, запуск приложения...");
  init();
});

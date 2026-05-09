import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';

// ========== Основные переменные ==========
let scene, camera, renderer, labelRenderer, controls;
let mainGroup;           // Группа для всей модели
let currentModel = null; // Текущая модель
let pointsCount = 0;

// Состояние измерения
let measuringMode = false;
let measurePoints = [];
let measureObjects = []; // Сферы и линии для отображения

// Состояние сечения
let sectionPlane = null;
let sectionPlaneVisible = false;
let isClipped = false;
let clipPlaneEquation = null;
let originalPositions = null; // Для копии оригинальных позиций

// UI элементы
let statsElement, coordsElement;
let lastTime = performance.now();
let frameCount = 0;

// ========== Инициализация ==========
function init() {
    // Сцена
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x30303a);
    scene.fog = new THREE.FogExp2(0x30303a, 0.0005);
    
    // Камера
    camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 10000);
    camera.position.set(500, 400, 600);
    camera.lookAt(0, 0, 0);
    
    // Рендереры
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true }); // preserveDrawingBuffer для скриншотов
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.shadowMap.enabled = false; // Отключаем тени для производительности
    renderer.setPixelRatio(window.devicePixelRatio);
    document.body.appendChild(renderer.domElement);
    
    // CSS2 рендерер для текста
    labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(window.innerWidth, window.innerHeight);
    labelRenderer.domElement.style.position = 'absolute';
    labelRenderer.domElement.style.top = '0px';
    labelRenderer.domElement.style.left = '0px';
    labelRenderer.domElement.style.pointerEvents = 'none';
    document.body.appendChild(labelRenderer.domElement);
    
    // Управление
    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.05;
    controls.rotateSpeed = 1.5;
    controls.zoomSpeed = 1.2;
    controls.panSpeed = 0.8;
    controls.enableZoom = true;
    controls.enablePan = true;
    
    // Группа для модели
    mainGroup = new THREE.Group();
    scene.add(mainGroup);
    
    // Вспомогательные объекты
    addGridHelper();
    addAxesHelper();
    
    // Статистика
    statsElement = document.getElementById('stats');
    coordsElement = document.getElementById('coords');
    
    // Запуск анимации
    animate();
    
    // Настройка обработчиков UI
    setupUI();
    
    // Обработка resize
    window.addEventListener('resize', onWindowResize, false);
    
    // Отображение координат
    setupCoordinateDisplay();
    
    console.log('Приложение инициализировано');
}

// ========== Вспомогательные элементы ==========
function addGridHelper() {
    // Основная сетка с шагом 100
    const gridHelper = new THREE.GridHelper(2000, 20, 0x888888, 0x444444);
    gridHelper.position.y = -0.1;
    gridHelper.material.transparent = true;
    gridHelper.material.opacity = 0.4;
    scene.add(gridHelper);
    
    // Дополнительная сетка с частыми линиями
    const fineGrid = new THREE.GridHelper(2000, 100, 0x666666, 0x333333);
    fineGrid.position.y = -0.1;
    fineGrid.material.transparent = true;
    fineGrid.material.opacity = 0.2;
    scene.add(fineGrid);
}

function addAxesHelper() {
    // Оси координат
    const axesHelper = new THREE.AxesHelper(500);
    axesHelper.material.transparent = true;
    axesHelper.material.opacity = 0.3;
    scene.add(axesHelper);
    
    // Добавляем подписи осей
    const makeAxisLabel = (text, color, position) => {
        const div = document.createElement('div');
        div.textContent = text;
        div.style.color = color;
        div.style.fontSize = '16px';
        div.style.fontWeight = 'bold';
        div.style.textShadow = '1px 1px 0px black';
        const label = new CSS2DObject(div);
        label.position.copy(position);
        scene.add(label);
    };
    
    makeAxisLabel('X', '#ff4444', new THREE.Vector3(550, 0, 0));
    makeAxisLabel('Y', '#44ff44', new THREE.Vector3(0, 550, 0));
    makeAxisLabel('Z', '#4444ff', new THREE.Vector3(0, 0, 550));
}

// ========== Парсинг G-code ==========
class GCodeParser {
    constructor() {
        this.points = [];
        this.segments = [];
    }
    
    parse(content) {
        this.points = [];
        this.segments = [];
        
        const lines = content.split('\n');
        let currentPos = { x: 0, y: 0, z: 0 };
        let currentPath = [currentPos];
        
        for (const line of lines) {
            if (!line.trim() || line.startsWith(';') || line.startsWith('(') || line.startsWith('%')) {
                continue;
            }
            
            const parts = line.trim().split(/\s+/);
            let isG1 = false;
            let newPos = { ...currentPos };
            let hasMove = false;
            
            for (const part of parts) {
                if (part === 'G1' || part === 'G01') {
                    isG1 = true;
                } else if (part.startsWith('X')) {
                    newPos.x = parseFloat(part.substring(1));
                    hasMove = true;
                } else if (part.startsWith('Y')) {
                    newPos.y = parseFloat(part.substring(1));
                    hasMove = true;
                } else if (part.startsWith('Z')) {
                    newPos.z = parseFloat(part.substring(1));
                    hasMove = true;
                }
            }
            
            if (isG1 && hasMove) {
                if (currentPath.length === 1 && (currentPath[0].x !== newPos.x || currentPath[0].y !== newPos.y || currentPath[0].z !== newPos.z)) {
                    currentPath.push(newPos);
                } else if (currentPath.length > 0) {
                    currentPath.push(newPos);
                }
                currentPos = newPos;
            } else if (hasMove) {
                // G0 или другое движение - завершаем текущий путь
                if (currentPath.length > 1) {
                    this.segments.push([...currentPath]);
                }
                currentPath = [newPos];
                currentPos = newPos;
            }
        }
        
        // Добавляем последний путь
        if (currentPath.length > 1) {
            this.segments.push([...currentPath]);
        }
        
        // Собираем все точки для центрирования
        for (const seg of this.segments) {
            for (const pt of seg) {
                this.points.push(pt);
            }
        }
        
        return this.segments.length > 0;
    }
    
    getBounds() {
        if (this.points.length === 0) return { min: {x:0,y:0,z:0}, max: {x:100,y:100,z:100} };
        
        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
        
        for (const pt of this.points) {
            minX = Math.min(minX, pt.x);
            minY = Math.min(minY, pt.y);
            minZ = Math.min(minZ, pt.z);
            maxX = Math.max(maxX, pt.x);
            maxY = Math.max(maxY, pt.y);
            maxZ = Math.max(maxZ, pt.z);
        }
        
        return {
            min: { x: minX, y: minY, z: minZ },
            max: { x: maxX, y: maxY, z: maxZ }
        };
    }
}

// ========== Создание 3D модели ==========
function createModelFromSegments(segments, color, lineWidth, opacity) {
    const group = new THREE.Group();
    
    // Материал для линий
    const material = new THREE.LineBasicMaterial({ color: color, linewidth: lineWidth });
    
    // Для каждой непрерывной линии создаём отдельный объект
    for (const segment of segments) {
        if (segment.length < 2) continue;
        
        const points = segment.map(p => new THREE.Vector3(p.x, p.z, p.y)); // Меняем Y и Z для удобства обзора
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const line = new THREE.Line(geometry, material);
        group.add(line);
    }
    
    return group;
}

// ========== Управление сечением (Clip Plane) ==========
function createSectionPlane() {
    if (sectionPlane) {
        scene.remove(sectionPlane);
        sectionPlane = null;
    }
    
    // Получаем границы модели
    let bounds = { min: {x:-300,y:-300,z:-300}, max: {x:300,y:300,z:300} };
    if (currentModel && currentModel.userData.bounds) {
        bounds = currentModel.userData.bounds;
    }
    
    const width = Math.abs(bounds.max.x - bounds.min.x);
    const height = Math.abs(bounds.max.z - bounds.min.z);
    const centerX = (bounds.min.x + bounds.max.x) / 2;
    const centerZ = (bounds.min.z + bounds.max.z) / 2;
    
    // Создаем прозрачную плоскость
    const geometry = new THREE.PlaneGeometry(width || 600, height || 600);
    const material = new THREE.MeshPhongMaterial({
        color: 0x00ffcc,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.4,
        emissive: 0x006666
    });
    
    sectionPlane = new THREE.Mesh(geometry, material);
    sectionPlane.position.set(centerX, 0, centerZ);
    sectionPlane.userData.isClipPlane = true;
    
    scene.add(sectionPlane);
    return sectionPlane;
}

function applyClipping(side) {
    if (!currentModel || !sectionPlane) return;
    
    const planePos = sectionPlane.position;
    const planeNormal = new THREE.Vector3(1, 0, 0); // Плоскость по X
    
    clipPlaneEquation = {
        normal: planeNormal,
        constant: -planePos.x
    };
    
    // Для каждой части модели применяем обрезку через шейдеры
    currentModel.children.forEach(child => {
        if (child.isLine) {
            child.material.clippingPlanes = [new THREE.Plane(planeNormal, -planePos.x)];
            child.material.transparent = true;
            
            // Инвертируем при необходимости
            if (side === 'right') {
                child.material.clippingPlanes[0].constant = planePos.x;
            } else {
                child.material.clippingPlanes[0].constant = -planePos.x;
            }
        }
    });
    
    isClipped = true;
}

function removeClipping() {
    if (!currentModel) return;
    
    currentModel.children.forEach(child => {
        if (child.isLine) {
            child.material.clippingPlanes = null;
        }
    });
    
    isClipped = false;
    clipPlaneEquation = null;
}

function hideSectionPlane() {
    if (sectionPlane) {
        sectionPlane.visible = false;
        sectionPlaneVisible = false;
    }
}

function showSectionPlane() {
    if (sectionPlane) {
        sectionPlane.visible = true;
        sectionPlaneVisible = true;
    } else {
        createSectionPlane();
        sectionPlaneVisible = true;
    }
}

function resetSection() {
    removeClipping();
    if (sectionPlane) {
        sectionPlane.visible = false;
    }
    sectionPlaneVisible = false;
    
    // Обновляем UI кнопок
    document.getElementById('clip-right-btn').disabled = true;
    document.getElementById('clip-left-btn').disabled = true;
    document.getElementById('hide-plane-btn').disabled = true;
    document.getElementById('show-plane-btn').disabled = false;
}

// ========== Измерения ==========
function startMeasurement() {
    measuringMode = true;
    measurePoints = [];
    // Очищаем предыдущие объекты измерения
    measureObjects.forEach(obj => scene.remove(obj));
    measureObjects = [];
    document.getElementById('measure-result').innerHTML = 'Расстояние: — <span style="color:#ff9800">(щелкните 2 точки на модели)</span>';
    document.getElementById('reset-measure-btn').disabled = false;
    
    // Добавляем слушатель кликов
    renderer.domElement.style.cursor = 'crosshair';
}

function resetMeasurement() {
    measuringMode = false;
    measurePoints = [];
    measureObjects.forEach(obj => scene.remove(obj));
    measureObjects = [];
    document.getElementById('measure-result').innerHTML = 'Расстояние: —';
    document.getElementById('reset-measure-btn').disabled = true;
    renderer.domElement.style.cursor = 'default';
}

function addMeasurementPoint(point) {
    // Создаем сферу в точке
    const geometry = new THREE.SphereGeometry(5, 16, 16);
    const material = new THREE.MeshStandardMaterial({ color: 0xff4444, emissive: 0x441111 });
    const sphere = new THREE.Mesh(geometry, material);
    sphere.position.copy(point);
    scene.add(sphere);
    measureObjects.push(sphere);
    
    // Добавляем точку
    measurePoints.push(point.clone());
    
    if (measurePoints.length === 2) {
        // Рисуем линию
        const points = [measurePoints[0], measurePoints[1]];
        const geometry = new THREE.BufferGeometry().setFromPoints(points);
        const material = new THREE.LineBasicMaterial({ color: 0x44ff44, linewidth: 2 });
        const line = new THREE.Line(geometry, material);
        scene.add(line);
        measureObjects.push(line);
        
        // Вычисляем расстояние
        const dist = measurePoints[0].distanceTo(measurePoints[1]);
        document.getElementById('measure-result').innerHTML = `📏 Расстояние: ${dist.toFixed(2)} мм`;
        
        // Добавляем текст в середине
        const midPoint = measurePoints[0].clone().add(measurePoints[1]).multiplyScalar(0.5);
        const div = document.createElement('div');
        div.textContent = `${dist.toFixed(1)} мм`;
        div.style.color = '#4caf50';
        div.style.fontSize = '14px';
        div.style.fontWeight = 'bold';
        div.style.backgroundColor = 'rgba(0,0,0,0.7)';
        div.style.padding = '2px 6px';
        div.style.borderRadius = '4px';
        div.style.border = '1px solid #4caf50';
        const label = new CSS2DObject(div);
        label.position.copy(midPoint);
        scene.add(label);
        measureObjects.push(label);
        
        // Завершаем режим измерения
        measuringMode = false;
        renderer.domElement.style.cursor = 'default';
        document.getElementById('measure-btn').classList.remove('active');
    }
}

// ========== Загрузка файла ==========
async function loadGCode(file) {
    const statusDiv = document.getElementById('file-status');
    statusDiv.innerHTML = '⏳ Загрузка и парсинг файла...';
    statusDiv.style.color = '#ff9800';
    
    try {
        const content = await file.text();
        const parser = new GCodeParser();
        
        statusDiv.innerHTML = '⏳ Обработка G-code...';
        
        if (parser.parse(content)) {
            const bounds = parser.getBounds();
            const segments = parser.segments;
            
            // Центрируем модель
            const centerX = (bounds.min.x + bounds.max.x) / 2;
            const centerZ = (bounds.min.z + bounds.max.z) / 2;
            const centerY = (bounds.min.y + bounds.max.y) / 2;
            
            // Сдвигаем все сегменты
            for (const seg of segments) {
                for (const pt of seg) {
                    pt.x -= centerX;
                    pt.y -= centerY;
                    pt.z -= centerZ;
                }
            }
            
            // Удаляем старую модель
            if (currentModel) {
                mainGroup.remove(currentModel);
                currentModel = null;
            }
            
            // Создаем новую
            const color = document.getElementById('color-picker').value;
            const thickness = parseInt(document.getElementById('thickness-slider').value);
            const opacity = parseInt(document.getElementById('opacity-slider').value) / 100;
            
            currentModel = createModelFromSegments(segments, color, thickness, opacity);
            currentModel.userData.bounds = bounds;
            currentModel.userData.segments = segments;
            currentModel.userData.originalPositions = JSON.parse(JSON.stringify(segments));
            
            mainGroup.add(currentModel);
            pointsCount = parser.points.length;
            
            statusDiv.innerHTML = `✅ Загружено: ${pointsCount.toLocaleString()} точек, ${segments.length} сегментов`;
            statusDiv.style.color = '#4caf50';
            
            // Сбрасываем сечение
            resetSection();
            
            // Настраиваем камеру
            const maxDim = Math.max(
                bounds.max.x - bounds.min.x,
                bounds.max.y - bounds.min.y,
                bounds.max.z - bounds.min.z
            );
            const distance = maxDim * 1.5;
            camera.position.set(distance * 0.8, distance * 0.6, distance);
            controls.target.set(0, 0, 0);
            controls.update();
            
        } else {
            statusDiv.innerHTML = '❌ Ошибка: Не удалось распарсить G-code';
            statusDiv.style.color = '#f44336';
        }
    } catch (err) {
        console.error(err);
        statusDiv.innerHTML = '❌ Ошибка при загрузке файла';
        statusDiv.style.color = '#f44336';
    }
}

// ========== Обновление внешнего вида ==========
function updateModelAppearance() {
    if (!currentModel) return;
    
    const color = document.getElementById('color-picker').value;
    const thickness = parseInt(document.getElementById('thickness-slider').value);
    const opacity = parseInt(document.getElementById('opacity-slider').value) / 100;
    
    currentModel.children.forEach(child => {
        if (child.isLine) {
            child.material.color.set(color);
            child.material.linewidth = thickness;
            child.material.opacity = opacity;
            child.material.transparent = opacity < 1;
        }
    });
}

// ========== Настройка UI ==========
function setupUI() {
    // Файл
    const fileInput = document.getElementById('file-input');
    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            loadGCode(e.target.files[0]);
        }
    });
    
    // Внешний вид
    document.getElementById('thickness-slider').addEventListener('input', (e) => {
        document.getElementById('thickness-value').textContent = e.target.value;
        updateModelAppearance();
    });
    
    document.getElementById('color-picker').addEventListener('input', () => updateModelAppearance());
    document.getElementById('opacity-slider').addEventListener('input', (e) => {
        document.getElementById('opacity-value').textContent = e.target.value + '%';
        updateModelAppearance();
    });
    
    document.getElementById('bg-color').addEventListener('input', (e) => {
        scene.background = new THREE.Color(e.target.value);
    });
    
    // Камера
    document.getElementById('cam-front').addEventListener('click', () => {
        camera.position.set(0, 0, 600);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-back').addEventListener('click', () => {
        camera.position.set(0, 0, -600);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-left').addEventListener('click', () => {
        camera.position.set(-600, 0, 0);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-right').addEventListener('click', () => {
        camera.position.set(600, 0, 0);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-top').addEventListener('click', () => {
        camera.position.set(0, 600, 0);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-bottom').addEventListener('click', () => {
        camera.position.set(0, -600, 0);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-iso').addEventListener('click', () => {
        camera.position.set(500, 400, 600);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    document.getElementById('cam-reset').addEventListener('click', () => {
        camera.position.set(500, 400, 600);
        controls.target.set(0, 0, 0);
        controls.update();
    });
    
    // Измерения
    document.getElementById('measure-btn').addEventListener('click', () => {
        if (measuringMode) {
            resetMeasurement();
        } else {
            startMeasurement();
        }
    });
    document.getElementById('reset-measure-btn').addEventListener('click', resetMeasurement);
    
    // Сечение
    document.getElementById('show-plane-btn').addEventListener('click', () => {
        showSectionPlane();
        document.getElementById('clip-right-btn').disabled = false;
        document.getElementById('clip-left-btn').disabled = false;
        document.getElementById('hide-plane-btn').disabled = false;
        document.getElementById('show-plane-btn').disabled = true;
    });
    document.getElementById('clip-right-btn').addEventListener('click', () => applyClipping('right'));
    document.getElementById('clip-left-btn').addEventListener('click', () => applyClipping('left'));
    document.getElementById('hide-plane-btn').addEventListener('click', hideSectionPlane);
    document.getElementById('reset-section-btn').addEventListener('click', resetSection);
    
    // Скриншот
    document.getElementById('screenshot-btn').addEventListener('click', () => {
        // Временно показываем плоскость если она скрыта
        const wasHidden = sectionPlane && !sectionPlane.visible;
        if (wasHidden) sectionPlane.visible = true;
        
        renderer.render(scene, camera);
        const dataURL = renderer.domElement.toDataURL('image/png');
        const link = document.createElement('a');
        link.href = dataURL;
        link.download = `gcode-screenshot-${Date.now()}.png`;
        link.click();
        
        if (wasHidden) sectionPlane.visible = false;
    });
    
    // Сворачивание панели
    let panelVisible = true;
    const panel = document.getElementById('ui-panel');
    const toggleBtn = document.getElementById('toggle-panel');
    toggleBtn.addEventListener('click', () => {
        panelVisible = !panelVisible;
        panel.style.display = panelVisible ? 'block' : 'none';
        toggleBtn.textContent = panelVisible ? '◀' : '▶';
        toggleBtn.style.left = panelVisible ? '340px' : '20px';
    });
}

// ========== Отображение координат ==========
function setupCoordinateDisplay() {
    // Raycaster для получения точки под курсором
    const raycaster = new THREE.Raycaster();
    const mouse = new THREE.Vector2();
    
    renderer.domElement.addEventListener('mousemove', (event) => {
        if (measuringMode) {
            // Вычисляем координаты для измерения
            mouse.x = (event.clientX / renderer.domElement.clientWidth) * 2 - 1;
            mouse.y = -(event.clientY / renderer.domElement.clientHeight) * 2 + 1;
            
            raycaster.setFromCamera(mouse, camera);
            if (currentModel) {
                const intersects = raycaster.intersectObjects(currentModel.children, true);
                if (intersects.length > 0) {
                    const point = intersects[0].point;
                    coordsElement.innerHTML = `📌 X: ${point.x.toFixed(1)} | Y: ${point.y.toFixed(1)} | Z: ${point.z.toFixed(1)}`;
                    return;
                }
            }
        }
        coordsElement.innerHTML = `📌 X: -- | Y: -- | Z: --`;
    });
    
    renderer.domElement.addEventListener('click', (event) => {
        if (measuringMode && currentModel) {
            mouse.x = (event.clientX / renderer.domElement.clientWidth) * 2 - 1;
            mouse.y = -(event.clientY / renderer.domElement.clientHeight) * 2 + 1;
            
            raycaster.setFromCamera(mouse, camera);
            const intersects = raycaster.intersectObjects(currentModel.children, true);
            if (intersects.length > 0) {
                addMeasurementPoint(intersects[0].point);
            }
        }
    });
}

// ========== Анимация и FPS ==========
function animate() {
    requestAnimationFrame(animate);
    
    // Обновляем controls
    controls.update();
    
    // Анимация плоскости сечения (вращение или эффект)
    if (sectionPlane && sectionPlane.visible) {
        const time = Date.now() * 0.002;
        const material = sectionPlane.material;
        material.emissiveIntensity = 0.3 + Math.sin(time) * 0.2;
    }
    
    // Рендеринг
    renderer.render(scene, camera);
    labelRenderer.render(scene, camera);
    
    // FPS счетчик
    frameCount++;
    const now = performance.now();
    if (now - lastTime >= 1000) {
        const fps = Math.round(frameCount * 1000 / (now - lastTime));
        statsElement.innerHTML = `⚡ ${fps} FPS | 📍 ${pointsCount.toLocaleString()} точек`;
        frameCount = 0;
        lastTime = now;
    }
}

// ========== Обработка resize ==========
function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
    labelRenderer.setSize(window.innerWidth, window.innerHeight);
}

// ========== Запуск ==========
init();
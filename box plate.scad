// Lid with selectable hole pattern
// pattern_mode:
// 0 = round grid
// 1 = honeycomb
// 2 = slots
// 3 = diagonal
// 4 = random tech pattern
// 5 = word "РОЗОЧКА"

box_x = 160;
box_y = 118;
top_thickness = 2;
lip_h = 5;
clearance = 0;
lip_wall = 1.2;
corner_r = 3;

border = 10;
hole_d = 2.4;
hole_pitch = 5.5;
slot_w = 1.2;
slot_l = 3.2;
pattern_mode = 5;

// for word pattern
letter_h = 8;
letter_w = 4;
text_size = 10;

module rounded_rect_2d(x, y, r){
    offset(r=r) offset(delta=-r) square([x, y], center=true);
}

module solid_lid(){
    linear_extrude(height=top_thickness)
        rounded_rect_2d(box_x, box_y, corner_r);
}

module inner_lip(){
    difference(){
        translate([0,0,-lip_h])
            linear_extrude(height=lip_h)
                rounded_rect_2d(box_x - 2*clearance, box_y - 2*clearance, max(0.1, corner_r-clearance));
        translate([0,0,-lip_h-0.1])
            linear_extrude(height=lip_h+0.2)
                rounded_rect_2d(box_x - 2*(clearance+lip_wall), box_y - 2*(clearance+lip_wall), max(0.1, corner_r-clearance-lip_wall));
    }
}

module round_grid(){
    for (y = [-(box_y/2)+border : hole_pitch : (box_y/2)-border])
        for (x = [-(box_x/2)+border : hole_pitch : (box_x/2)-border])
            translate([x, y, -0.1])
                cylinder(h=top_thickness+0.2, d=hole_d, $fn=24);
}

module honeycomb(){
    step_y = hole_pitch * 0.8660254;
    for (row = [-50:50]) {
        y = row * step_y;
        xoff = (row % 2) * hole_pitch / 2;
        for (col = [-50:50]) {
            x = col * hole_pitch + xoff;
            if (abs(x) < box_x/2 - border && abs(y) < box_y/2 - border)
                translate([x, y, -0.1])
                    cylinder(h=top_thickness+0.2, d=hole_d, $fn=6);
        }
    }
}

module slots(){
    step_x = 6.5;
    step_y = 6.5;
    for (y = [-(box_y/2)+border : step_y : (box_y/2)-border])
        for (x = [-(box_x/2)+border : step_x : (box_x/2)-border])
            translate([x, y, -0.1])
                rotate(((x+y)*13) % 180)
                    linear_extrude(height=top_thickness+0.2)
                        square([slot_l, slot_w], center=true);
}

module diagonal_pattern(){
    step = 5.0;
    for (i = [-80:80]) {
        x = i * step;
        y = x * 0.35;
        if (abs(x) < box_x/2 - border && abs(y) < box_y/2 - border)
            translate([x, y, -0.1])
                cylinder(h=top_thickness+0.2, d=hole_d, $fn=20);
        y2 = -x * 0.35;
        if (abs(x) < box_x/2 - border && abs(y2) < box_y/2 - border)
            translate([x, y2, -0.1])
                cylinder(h=top_thickness+0.2, d=hole_d, $fn=20);
    }
}

module random_tech_pattern(){
    pts = [
        [-44,-26],[-37,-18],[-29,-24],[-22,-14],[-15,-22],[-8,-16],[-2,-25],[6,-18],[14,-27],[21,-15],
        [28,-22],[36,-17],[43,-24],[-41,-6],[-33,-10],[-25,-4],[-17,-9],[-9,-2],[-1,-8],[8,-4],
        [16,-10],[24,-3],[32,-8],[40,-2],[-45,8],[-37,2],[-29,10],[-21,4],[-13,11],[-5,5],
        [3,12],[11,4],[19,10],[27,3],[35,9],[43,2],[-40,20],[-31,15],[-23,22],[-15,16],
        [-7,24],[1,17],[9,23],[17,15],[25,21],[33,16],[41,22]
    ];
    for (p = pts)
        if (abs(p[0]) < box_x/2 - border && abs(p[1]) < box_y/2 - border)
            translate([p[0], p[1], -0.1])
                cylinder(h=top_thickness+0.2, d=hole_d, $fn=5 + (abs(p[0]+p[1]) % 4));
}

module word_rozochka(){
    translate([0, 0, -0.1])
        linear_extrude(height=top_thickness+0.2)
            text("РОЗОЧКА", size=text_size, halign="center", valign="center", font="DejaVu Sans");
}

module fill_with_microholes(){
    for (y = [-(box_y/2)+border : hole_pitch : (box_y/2)-border])
        for (x = [-(box_x/2)+border : hole_pitch : (box_x/2)-border])
            if (!(abs(x)<35 && abs(y)<10))
                translate([x, y, -0.1])
                    cylinder(h=top_thickness+0.2, d=2, $fn=18);
}

difference(){
    union(){
        solid_lid();
        inner_lip();
    }

    if (pattern_mode == 0) round_grid();
    else if (pattern_mode == 1) honeycomb();
    else if (pattern_mode == 2) slots();
    else if (pattern_mode == 3) diagonal_pattern();
    else if (pattern_mode == 4) random_tech_pattern();
    else if (pattern_mode == 5) {
        fill_with_microholes();
        word_rozochka();
    }
}

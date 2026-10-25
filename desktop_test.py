import canvas_studio as studio
import random

def draw():
    studio.clear()
    
    global angle
    angle = angle + 1
    studio.rect(studio.mouse_x, studio.mouse_y, 100, 100, origin=(.5, .5), rotate=-angle)
    # studio.image(img_lion, studio.mouse_x, studio.mouse_y, 100, 100, origin=(.5, .5), rotate=angle)
    
    studio.line(studio.mouse_x, studio.mouse_y, 300, 300, width=10)
    
    # Iterate backwards so we can safely remove elements without breaking the loop
    for i in range(len(firework_list) - 1, -1, -1):
        f = firework_list[i]
        
        # Draw the particle
        studio.image(img_lion, f[0], f[1], 30, 30, origin=(.5, .5), rotate=random.randint(0,360))
        
        # Update position (x, y) using velocity (vx, vy)
        f[0] += f[2]
        f[1] += f[3]
        
        # Apply physics (air resistance and gravity)
        f[2] *= 0.98   # Horizontal drag
        f[3] += 0.2    # Gravity pulling downward
        
        # Remove particle if it goes completely off-screen (prevents memory leaks)
        if f[1] > height or f[1] < 0 or f[0] < 0 or f[0] > width:
            firework_list.pop(i)

def mousePressed():
    mouse_x = studio.mouse_x
    mouse_y = studio.mouse_y
    # Increased initial positions and speeds so the firework bursts outward nicely
    firework_list.append([mouse_x, mouse_y, 4, 0]) # bursts toward the right
    firework_list.append([mouse_x, mouse_y, 3, 3]) # bursts diagonally down-right
    firework_list.append([mouse_x, mouse_y, 0, 4]) # bursts straight down
    firework_list.append([mouse_x, mouse_y, -3, 3]) # bursts diagonally down-left
    firework_list.append([mouse_x, mouse_y, -4, 0]) # bursts toward the left
    firework_list.append([mouse_x, mouse_y, -3, -3]) # bursts diagonally up-left
    firework_list.append([mouse_x, mouse_y, 0, -4]) # bursts straight up
    firework_list.append([mouse_x, mouse_y, 3, -3]) # bursts diagonally up-right

img_lion = studio.load_image('lion.png')
firework_list = []
width, height = 600, 600
angle = 0

studio.set_canvas_size(width, height)
studio.start(draw, mousePressed=mousePressed)

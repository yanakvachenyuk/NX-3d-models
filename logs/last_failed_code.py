base = Parallelogram(workPart, side_a=200.0, side_b=80.0, angle=90.0)
wheel_base_1 = Circle(workPart, radius=20.0, center=base.point_from_center(-60.0, -30.0))
wheel_base_2 = Circle(workPart, radius=20.0, center=base.point_from_center(60.0, -30.0))
bus_body = Extrude(workPart, [base, wheel_base_1, wheel_base_2], height=40.0)
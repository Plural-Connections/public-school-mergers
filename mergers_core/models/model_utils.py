from mergers_core.utils.header import *
from mergers_core.models.constants import *


def estimate_travel_time_impacts(
    state,
    school_cluster_lists,
    df_grades_curr,
    df_schools_in_play,
    blocks_file="data/attendance_boundaries/2122/{}/estimated_student_counts_per_block.csv",
    travel_times_file="data/travel_times_files/2122/{}/block_to_school_driving_times.json",
):
    df_b = pd.read_csv(
        blocks_file.format(state), dtype={"ncessch": str, "block_id": str}
    )
    travel_times = read_dict(travel_times_file.format(state))
    cat_cols = [c for c in df_b.keys() if c.startswith("num_")]

    # Compute status quo total driving times per cat
    status_quo_total_driving_times_per_cat = Counter()
    for i in range(0, len(df_schools_in_play)):
        nces_id = df_schools_in_play["NCESSCH"][i]
        df_b_s = df_b[df_b["ncessch"] == nces_id].reset_index(drop=True)
        for c in cat_cols:
            for j in range(0, len(df_b_s)):
                driving_time_b_s = travel_times[df_b_s["block_id"][j]][nces_id]
                if driving_time_b_s and not np.isnan(driving_time_b_s):
                    status_quo_total_driving_times_per_cat[
                        f"all_status_quo_time_{c}"
                    ] += (driving_time_b_s * df_b_s[c][j])

    # Now, compute how many students we expect to switch from a given school A to a given school B, per cat
    # and compute the estimated travel times for those students
    num_students_switching_per_school_per_cat = defaultdict(dict)
    clusters = [c.split(", ") for c in school_cluster_lists]
    merged_schools = filter(lambda x: len(x) > 1, clusters)
    schools_serving_each_grade_per_cluster = defaultdict(dict)

    race_keys = list(RACE_KEYS.values())
    for cluster in merged_schools:
        cluster_key = ", ".join(cluster)

        # Determine which grades are served by which schools in a given cluster
        for s in cluster:
            s_school_grades = df_grades_curr[df_grades_curr["NCESSCH"] == s].iloc[0]
            for g in GRADE_TO_IND:
                if s_school_grades[g]:
                    schools_serving_each_grade_per_cluster[cluster_key][g] = s
        for s in cluster:
            s_school_enrollments = df_schools_in_play[
                df_schools_in_play["NCESSCH"] == s
            ].iloc[0]
            for g in GRADE_TO_IND:
                school_serving_g = schools_serving_each_grade_per_cluster[cluster_key][
                    g
                ]
                if s != school_serving_g:
                    if (
                        not school_serving_g
                        in num_students_switching_per_school_per_cat[s]
                    ):
                        num_students_switching_per_school_per_cat[s][
                            school_serving_g
                        ] = Counter()
                    for r in race_keys:
                        num_students_switching_per_school_per_cat[s][school_serving_g][
                            r
                        ] += s_school_enrollments[f"{r}_{g}"]

    # Now, estimate changes in driving times for students switching schools
    status_quo_total_driving_times_for_switchers_per_cat = Counter()
    status_quo_total_driving_times_for_switchers_per_school_per_cat = defaultdict(
        Counter
    )
    new_total_driving_times_for_switchers_per_cat = Counter()
    new_total_driving_times_for_switchers_per_school_per_cat = defaultdict(Counter)
    for s in num_students_switching_per_school_per_cat:
        df_b_s = df_b[df_b["ncessch"] == s].reset_index(drop=True)
        for s2 in num_students_switching_per_school_per_cat[s]:
            switchers_per_block_and_cat = defaultdict(Counter)
            for c in cat_cols:
                # Determine est number of switchers per block (decimal students are fine)
                df_b_s[f"per_of_total_{c}"] = df_b_s[c] / df_b_s[c].sum()
                df_b_s = df_b_s.fillna(0)
                for i in range(0, len(df_b_s)):
                    switchers_per_block_and_cat[df_b_s["block_id"][i]][c] += (
                        df_b_s[f"per_of_total_{c}"][i]
                        * num_students_switching_per_school_per_cat[s][s2][c]
                    )
                    # Estimate status quo and new travel times (# per block x travel time per block)
                    if travel_times[df_b_s["block_id"][i]][s] and not np.isnan(
                        travel_times[df_b_s["block_id"][i]][s]
                    ):
                        status_quo_total_driving_times_for_switchers_per_cat[
                            f"switcher_status_quo_time_{c}"
                        ] += (
                            switchers_per_block_and_cat[df_b_s["block_id"][i]][c]
                            * travel_times[df_b_s["block_id"][i]][s]
                        )
                        status_quo_total_driving_times_for_switchers_per_school_per_cat[
                            s
                        ][f"switcher_status_quo_time_{c}"] += (
                            switchers_per_block_and_cat[df_b_s["block_id"][i]][c]
                            * travel_times[df_b_s["block_id"][i]][s]
                        )
                    if travel_times[df_b_s["block_id"][i]][s2] and not np.isnan(
                        travel_times[df_b_s["block_id"][i]][s2]
                    ):
                        new_total_driving_times_for_switchers_per_cat[
                            f"switcher_new_time_{c}"
                        ] += (
                            switchers_per_block_and_cat[df_b_s["block_id"][i]][c]
                            * travel_times[df_b_s["block_id"][i]][s2]
                        )
                        new_total_driving_times_for_switchers_per_school_per_cat[s][
                            f"switcher_new_time_{c}"
                        ] += (
                            switchers_per_block_and_cat[df_b_s["block_id"][i]][c]
                            * travel_times[df_b_s["block_id"][i]][s2]
                        )

    return (
        status_quo_total_driving_times_per_cat,
        status_quo_total_driving_times_for_switchers_per_cat,
        new_total_driving_times_for_switchers_per_cat,
        status_quo_total_driving_times_for_switchers_per_school_per_cat,
        new_total_driving_times_for_switchers_per_school_per_cat,
    )


def check_solution_validity_and_compute_outcomes(
    df_mergers_g, df_grades, df_schools_in_play, state, pre_or_post="post"
):
    # print(pre_or_post)
    race_keys = list(RACE_KEYS.values())
    df_mergers_curr = df_mergers_g.copy(deep=True)
    df_grades_curr = df_grades.copy(deep=True)
    if pre_or_post == "pre":
        df_mergers_curr = pd.DataFrame(
            {"school_cluster": df_grades["NCESSCH"].tolist()}
        )
        for g in GRADE_TO_IND:
            df_grades_curr[g] = [True for i in range(0, len(df_grades))]

    # Make a dataframe based on which grades are offered by which schools
    school_cluster_lists = df_mergers_curr["school_cluster"].tolist()

    grades_served_per_cluster = defaultdict(set)
    school_clusters = defaultdict(list)
    for c in school_cluster_lists:
        schools = c.split(", ")
        for s in schools:
            school_clusters[s] = schools
            s_school_grades = df_grades_curr[df_grades_curr["NCESSCH"] == s].iloc[0]
            for g in GRADE_TO_IND:
                if s_school_grades[g]:
                    grades_served_per_cluster[c].add(g)

    num_per_cat_per_school = defaultdict(Counter)
    num_per_school_per_grade_per_cat = {}
    # grades_served_across_matched_schools = defaultdict(set)
    for s in school_clusters:
        s_school_grades = df_grades_curr[df_grades_curr["NCESSCH"] == s].iloc[0]
        num_per_school_per_grade_per_cat[s] = {r: Counter() for r in race_keys}
        for s2 in school_clusters[s]:
            s2_school_enrollments = df_schools_in_play[
                df_schools_in_play["NCESSCH"] == s2
            ].iloc[0]
            for g in GRADE_TO_IND:
                if s_school_grades[g]:
                    for r in race_keys:
                        num_per_cat_per_school[r][s] += s2_school_enrollments[
                            f"{r}_{g}"
                        ]
                        num_per_school_per_grade_per_cat[s][r][
                            g
                        ] += s2_school_enrollments[f"{r}_{g}"]

    ##### Now that we've built some helpful data structures above, do some solution validity checking

    # First, check if all students are accounted for in the re-assignment
    total_cols = [f"num_total_{g}" for g in GRADE_TO_IND]
    total_students_dict = sum(num_per_cat_per_school["num_total"].values())
    total_students_df = df_schools_in_play[total_cols].sum(axis=1).sum()

    # Next, check if all grades are represented across a cluster
    for c in grades_served_per_cluster:
        if len(grades_served_per_cluster[c]) != len(GRADE_TO_IND):
            raise Exception(
                f"Only {len(grades_served_per_cluster[c])} of {len(GRADE_TO_IND)} grades represented across cluster {c}"
            )

    if total_students_dict != total_students_df:
        print(total_students_dict, total_students_df)
        raise Exception("All students not accounted for in re-assignment")

    # Next, make sure that grades assigned to schools are contiguous
    for i in range(0, len(df_grades_curr)):
        curr_grade_seq = df_grades_curr[list(GRADE_TO_IND.keys())].iloc[i].tolist()
        start_grade = None
        end_grade = None
        for i, g in enumerate(curr_grade_seq):
            if g and not start_grade:
                start_grade = g
                continue
            if start_grade and not g:
                end_grade = curr_grade_seq[i - 1]
                continue
            if start_grade and end_grade and g:
                raise Exception(
                    f"Grade levels schools are serving are not contiguous: {df_grades_curr['NCESSCH'][i]}, {', '.join(curr_grade_seq)}"
                )

    ##### End solution quality checking

    # Now, go through and compute dissim values for white/non-white
    dissim_vals = []
    for s in school_clusters:
        dissim_vals.append(
            np.abs(
                (
                    num_per_cat_per_school["num_white"][s]
                    / sum(num_per_cat_per_school["num_white"].values())
                )
                - (
                    (
                        num_per_cat_per_school["num_total"][s]
                        - num_per_cat_per_school["num_white"][s]
                    )
                    / (
                        sum(num_per_cat_per_school["num_total"].values())
                        - sum(num_per_cat_per_school["num_white"].values())
                    )
                )
            )
        )

    dissim_val = 0.5 * np.sum(dissim_vals)

    # Now, go through and compute dissim values for black-hispanic and white-asian
    bh_wa_dissim_vals = []
    for s in school_clusters:
        bh_wa_dissim_vals.append(
            np.abs(
                (
                    (
                        num_per_cat_per_school["num_black"][s]
                        + num_per_cat_per_school["num_hispanic"][s]
                    )
                    / (
                        sum(num_per_cat_per_school["num_black"].values())
                        + sum(num_per_cat_per_school["num_hispanic"].values())
                    )
                )
                - (
                    (
                        num_per_cat_per_school["num_white"][s]
                        + num_per_cat_per_school["num_asian"][s]
                    )
                    / (
                        sum(num_per_cat_per_school["num_white"].values())
                        + sum(num_per_cat_per_school["num_asian"].values())
                    )
                )
            )
        )

    bh_wa_dissim_val = 0.5 * np.sum(bh_wa_dissim_vals)

    # Now, go through and compute the number of students per group who will switch schools
    clusters = [c.split(", ") for c in school_cluster_lists]
    # merged_schools = filter(lambda x: len(x) > 1, clusters)
    num_students_switching = {f"{r}_switched": 0 for r in race_keys}
    num_students_switching_per_school = {}
    num_total_students = {f"{r}_all": 0 for r in race_keys}
    schools = []
    for cluster in clusters:
        for s in cluster:
            schools.append(s)
            s_school_grades = df_grades_curr[df_grades_curr["NCESSCH"] == s].iloc[0]
            s_school_enrollments = df_schools_in_play[
                df_schools_in_play["NCESSCH"] == s
            ].iloc[0]
            num_students_switching_per_school[s] = {
                f"{r}_switched": 0 for r in race_keys
            }
            for g in GRADE_TO_IND:
                for r in race_keys:
                    num_total_students[f"{r}_all"] += s_school_enrollments[f"{r}_{g}"]
                    if not s_school_grades[g]:
                        num_students_switching[f"{r}_switched"] += s_school_enrollments[
                            f"{r}_{g}"
                        ]
                        num_students_switching_per_school[s][
                            f"{r}_switched"
                        ] += s_school_enrollments[f"{r}_{g}"]

    # print(num_total_students)
    # print(schools)
    # exit()
    # Now, go through and estimate impacts on travel times
    (
        status_quo_total_driving_times_per_cat,
        status_quo_total_driving_times_for_switchers_per_cat,
        new_total_driving_times_for_switchers_per_cat,
        status_quo_total_driving_times_for_switchers_per_school_per_cat,
        new_total_driving_times_for_switchers_per_school_per_cat,
    ) = estimate_travel_time_impacts(
        state,
        school_cluster_lists,
        df_grades_curr,
        df_schools_in_play,
    )

    # Return results
    return (
        dissim_val,
        bh_wa_dissim_val,
        num_per_cat_per_school,
        num_per_school_per_grade_per_cat,
        num_total_students,
        num_students_switching,
        num_students_switching_per_school,
        status_quo_total_driving_times_per_cat,
        status_quo_total_driving_times_for_switchers_per_cat,
        new_total_driving_times_for_switchers_per_cat,
        status_quo_total_driving_times_for_switchers_per_school_per_cat,
        new_total_driving_times_for_switchers_per_school_per_cat,
    )


def output_solver_solution(
    solver,
    matches,
    grades_interval_binary,
    state,
    district_id,
    school_decrease_threshold,
    interdistrict,
    df_schools_in_play,
    output_dir,
    s3_bucket,
    write_to_s3,
    mergers_file_name,
    grades_served_file_name,
    schools_in_play_file_name,
    results_file_name="analytics.csv",
    students_switching_per_group_per_school_file="students_switching_per_group_per_school.json",
    students_per_group_per_school_post_merger_file="students_per_group_per_school_post_merger.json",
    students_per_grade_per_group_per_school_post_merger_file="students_per_grade_per_group_per_school_post_merger.json",
    status_quo_total_driving_times_for_switchers_per_school_per_cat_file="status_quo_total_driving_times_for_switchers_per_school_per_cat.json",
    new_total_driving_times_for_switchers_per_school_per_cat_file="new_total_driving_times_for_switchers_per_school_per_cat.json",
):

    # Extract solver variables
    match_data = {"school_1": [], "school_2": []}
    grades_served_data = {"NCESSCH": []}
    grades_served_data.update({g: [] for g in GRADE_TO_IND.keys()})
    ind_to_grade = [k for k in GRADE_TO_IND]
    for s in matches:
        for s2 in matches[s]:
            val = solver.BooleanValue(matches[s][s2])
            if val:
                match_data["school_1"].append(s)
                match_data["school_2"].append(s2)

        grades_served_data["NCESSCH"].append(s)
        for i in range(0, len(grades_interval_binary[s])):
            val = solver.BooleanValue(grades_interval_binary[s][i])
            grades_served_data[ind_to_grade[i]].append(val)

    if write_to_s3:
        output_dir = s3_bucket + output_dir
    else:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    df_mergers = pd.DataFrame(match_data)
    df_mergers_g = (
        df_mergers.groupby("school_1", as_index=False)
        .agg({"school_2": ", ".join})
        .drop_duplicates(subset="school_2")
        .drop(columns=["school_1"])
        .rename(columns={"school_2": "school_cluster"})
    )
    df_grades = pd.DataFrame(grades_served_data)
    df_mergers_g.to_csv(os.path.join(output_dir, mergers_file_name), index=False)
    df_grades.to_csv(os.path.join(output_dir, grades_served_file_name), index=False)
    df_schools_in_play.to_csv(
        os.path.join(output_dir, schools_in_play_file_name), index=False
    )

    # Compute pre/post dissim and other outcomes of interest
    try:
        pre_dissim, pre_dissim_bh_wa, _, _, _, _, _, _, _, _, _, _ = (
            check_solution_validity_and_compute_outcomes(
                df_mergers_g, df_grades, df_schools_in_play, state, pre_or_post="pre"
            )
        )

        (
            post_dissim,
            post_dissim_bh_wa,
            num_per_cat_per_school,
            num_per_school_per_grade_per_cat,
            num_total_students,
            num_students_switching,
            num_students_switching_per_school,
            status_quo_total_driving_times_per_cat,
            status_quo_total_driving_times_for_switchers_per_cat,
            new_total_driving_times_for_switchers_per_cat,
            status_quo_total_driving_times_for_switchers_per_school_per_cat,
            new_total_driving_times_for_switchers_per_school_per_cat,
        ) = check_solution_validity_and_compute_outcomes(
            df_mergers_g, df_grades, df_schools_in_play, state, pre_or_post="post"
        )

    except Exception as e:
        print(f"ERROR!!!! {e}")
        errors = {"error_message": str(e)}
        write_dict(os.path.join(output_dir, "errors.json"), errors)
        return

    # Output results
    data_to_output = {
        "state": state,
        "district_id": district_id,
        "school_decrease_threshold": school_decrease_threshold,
        "interdistrict": bool(interdistrict),
        "pre_dissim": pre_dissim,
        "post_dissim": post_dissim,
        "pre_dissim_bh_wa": pre_dissim_bh_wa,
        "post_dissim_bh_wa": post_dissim_bh_wa,
    }
    data_to_output.update(num_total_students)
    data_to_output.update(num_students_switching)
    data_to_output.update(status_quo_total_driving_times_per_cat)
    data_to_output.update(status_quo_total_driving_times_for_switchers_per_cat)
    data_to_output.update(new_total_driving_times_for_switchers_per_cat)
    # print(json.dumps(data_to_output, indent=4))

    print(
        f"Pre dissim: {pre_dissim}\n",
        f"Post dissim: {post_dissim}\n",
        f"Pre bh-wa dissim: {pre_dissim_bh_wa}\n",
        f"Post bh-wa dissim: {post_dissim_bh_wa}\n",
    )
    try:
        print(
            f"Percent switchers: {num_students_switching['num_total_switched'] / num_total_students['num_total_all']}\n",
            f"SQ avg. travel time - all: {status_quo_total_driving_times_per_cat['all_status_quo_time_num_total']/ num_total_students['num_total_all']/ 60}\n",
            f"SQ avg. travel time - switchers: {status_quo_total_driving_times_for_switchers_per_cat['switcher_status_quo_time_num_total']/ num_students_switching['num_total_switched']/ 60}\n",
            f"New avg. travel time - switchers: {new_total_driving_times_for_switchers_per_cat['switcher_new_time_num_total']/num_students_switching['num_total_switched']/ 60}\n",
        )
    except Exception as e:
        pass

    pd.DataFrame(data_to_output, index=[0]).to_csv(
        os.path.join(output_dir, results_file_name), index=False
    )

    # Output number of students per race, per school
    if write_to_s3:
        from s3fs import S3FileSystem

        path_to_s3_obj = os.path.join(
            output_dir, students_switching_per_group_per_school_file
        )
        s3 = S3FileSystem()
        with s3.open(path_to_s3_obj, "w") as file:
            json.dump(num_students_switching_per_school, file)

        path_to_s3_obj = os.path.join(
            output_dir, students_per_group_per_school_post_merger_file
        )
        s3 = S3FileSystem()
        with s3.open(path_to_s3_obj, "w") as file:
            json.dump(num_per_cat_per_school, file)

        path_to_s3_obj = os.path.join(
            output_dir, students_per_grade_per_group_per_school_post_merger_file
        )
        s3 = S3FileSystem()
        with s3.open(path_to_s3_obj, "w") as file:
            json.dump(num_per_school_per_grade_per_cat, file)

        path_to_s3_obj = os.path.join(
            output_dir,
            status_quo_total_driving_times_for_switchers_per_school_per_cat_file,
        )
        s3 = S3FileSystem()
        with s3.open(path_to_s3_obj, "w") as file:
            json.dump(
                status_quo_total_driving_times_for_switchers_per_school_per_cat,
                file,
            )

        path_to_s3_obj = os.path.join(
            output_dir, new_total_driving_times_for_switchers_per_school_per_cat_file
        )
        s3 = S3FileSystem()
        with s3.open(path_to_s3_obj, "w") as file:
            json.dump(new_total_driving_times_for_switchers_per_school_per_cat, file)

    else:

        write_dict(
            os.path.join(output_dir, students_switching_per_group_per_school_file),
            num_students_switching_per_school,
        )

        write_dict(
            os.path.join(output_dir, students_per_group_per_school_post_merger_file),
            num_per_cat_per_school,
        )

        write_dict(
            os.path.join(
                output_dir, students_per_grade_per_group_per_school_post_merger_file
            ),
            num_per_school_per_grade_per_cat,
        )

        write_dict(
            os.path.join(
                output_dir,
                status_quo_total_driving_times_for_switchers_per_school_per_cat_file,
            ),
            status_quo_total_driving_times_for_switchers_per_school_per_cat,
        )

        write_dict(
            os.path.join(
                output_dir,
                new_total_driving_times_for_switchers_per_school_per_cat_file,
            ),
            new_total_driving_times_for_switchers_per_school_per_cat,
        )


"""
Produces post solver / analysis files in case the jobs running on the server failed to produce some
"""


def produce_post_solver_files(
    df_mergers_g,
    df_grades,
    df_schools_in_play,
    state,
    district_id,
    school_decrease_threshold,
    interdistrict,
    output_dir,
    results_file_name="analytics.csv",
    students_switching_per_group_per_school_file="students_switching_per_group_per_school.json",
    students_per_group_per_school_post_merger_file="students_per_group_per_school_post_merger.json",
    students_per_grade_per_group_per_school_post_merger_file="students_per_grade_per_group_per_school_post_merger.json",
    status_quo_total_driving_times_for_switchers_per_school_per_cat_file="status_quo_total_driving_times_for_switchers_per_school_per_cat.json",
    new_total_driving_times_for_switchers_per_school_per_cat_file="new_total_driving_times_for_switchers_per_school_per_cat.json",
):
    # Compute pre/post dissim and other outcomes of interest
    try:
        pre_dissim, pre_dissim_bh_wa, _, _, _, _, _, _, _, _, _, _ = (
            check_solution_validity_and_compute_outcomes(
                df_mergers_g, df_grades, df_schools_in_play, state, pre_or_post="pre"
            )
        )

        (
            post_dissim,
            post_dissim_bh_wa,
            num_per_cat_per_school,
            num_per_school_per_grade_per_cat,
            num_total_students,
            num_students_switching,
            num_students_switching_per_school,
            status_quo_total_driving_times_per_cat,
            status_quo_total_driving_times_for_switchers_per_cat,
            new_total_driving_times_for_switchers_per_cat,
            status_quo_total_driving_times_for_switchers_per_school_per_cat,
            new_total_driving_times_for_switchers_per_school_per_cat,
        ) = check_solution_validity_and_compute_outcomes(
            df_mergers_g, df_grades, df_schools_in_play, state, pre_or_post="post"
        )

    except Exception as e:
        print(f"ERROR!!!! {e}")
        errors = {"error_message": str(e)}
        write_dict(os.path.join(output_dir, "errors.json"), errors)
        return

    # Output results
    data_to_output = {
        "state": state,
        "district_id": district_id,
        "school_decrease_threshold": school_decrease_threshold,
        "interdistrict": bool(interdistrict),
        "pre_dissim": pre_dissim,
        "post_dissim": post_dissim,
        "pre_dissim_bh_wa": pre_dissim_bh_wa,
        "post_dissim_bh_wa": post_dissim_bh_wa,
    }
    data_to_output.update(num_total_students)
    data_to_output.update(num_students_switching)
    data_to_output.update(status_quo_total_driving_times_per_cat)
    data_to_output.update(status_quo_total_driving_times_for_switchers_per_cat)
    data_to_output.update(new_total_driving_times_for_switchers_per_cat)
    # print(json.dumps(data_to_output, indent=4))

    print(
        f"Pre dissim: {pre_dissim}\n",
        f"Post dissim: {post_dissim}\n",
        f"Pre bh-wa dissim: {pre_dissim_bh_wa}\n",
        f"Post bh-wa dissim: {post_dissim_bh_wa}\n",
    )
    try:
        print(
            f"Percent switchers: {num_students_switching['num_total_switched'] / num_total_students['num_total_all']}\n",
            f"SQ avg. travel time - all: {status_quo_total_driving_times_per_cat['all_status_quo_time_num_total']/ num_total_students['num_total_all']/ 60}\n",
            f"SQ avg. travel time - switchers: {status_quo_total_driving_times_for_switchers_per_cat['switcher_status_quo_time_num_total']/ num_students_switching['num_total_switched']/ 60}\n",
            f"New avg. travel time - switchers: {new_total_driving_times_for_switchers_per_cat['switcher_new_time_num_total']/num_students_switching['num_total_switched']/ 60}\n",
        )
    except Exception as e:
        pass

    try:
        pd.DataFrame(data_to_output, index=[0]).to_csv(
            os.path.join(output_dir, results_file_name), index=False
        )

        write_dict(
            os.path.join(output_dir, students_switching_per_group_per_school_file),
            num_students_switching_per_school,
        )

        write_dict(
            os.path.join(output_dir, students_per_group_per_school_post_merger_file),
            num_per_cat_per_school,
        )

        write_dict(
            os.path.join(
                output_dir, students_per_grade_per_group_per_school_post_merger_file
            ),
            num_per_school_per_grade_per_cat,
        )

        write_dict(
            os.path.join(
                output_dir,
                status_quo_total_driving_times_for_switchers_per_school_per_cat_file,
            ),
            status_quo_total_driving_times_for_switchers_per_school_per_cat,
        )

        write_dict(
            os.path.join(
                output_dir,
                new_total_driving_times_for_switchers_per_school_per_cat_file,
            ),
            new_total_driving_times_for_switchers_per_school_per_cat,
        )

    except Exception as e:
        pass


def produce_post_solver_files_parallel(
    batch="min_elem_4_interdistrict_bottom_sensitivity",
    solutions_dir="data/results/{}/",
):
    # Compute pre/post dissim and other outcomes of interest
    all_jobs = []
    for state in os.listdir(solutions_dir.format(batch)):
        print(state)
        if "consolidated" in state:
            continue
        for district_id in os.listdir(os.path.join(solutions_dir.format(batch), state)):
            try:
                curr_dir = os.path.join(
                    solutions_dir.format(batch),
                    state,
                    district_id,
                )
                soln_dirs = os.listdir(curr_dir)
                for dir in soln_dirs:
                    if ".html" in dir:
                        continue
                    this_dir = os.path.join(curr_dir, dir)
                    df_mergers_g = pd.read_csv(
                        glob.glob(
                            os.path.join(
                                this_dir,
                                "**/" + "school_mergers.csv",
                            ),
                            recursive=True,
                        )[0],
                        dtype=str,
                    )
                    df_grades = pd.read_csv(
                        glob.glob(
                            os.path.join(
                                this_dir,
                                "**/" + "grades_served.csv",
                            ),
                            recursive=True,
                        )[0],
                        dtype={"NCESSCH": str},
                    )
                    df_schools_in_play = pd.read_csv(
                        glob.glob(
                            os.path.join(
                                this_dir,
                                "**/" + "schools_in_play.csv",
                            ),
                            recursive=True,
                        )[0],
                        dtype={"NCESSCH": str},
                    )
                    this_dir_root = this_dir.split("/")[-1].split("_")
                    interdistrict = False if this_dir_root[0] == "False" else True
                    school_decrease_threshold = float(this_dir_root[1])

                    all_jobs.append(
                        (
                            df_mergers_g,
                            df_grades,
                            df_schools_in_play,
                            state,
                            district_id,
                            school_decrease_threshold,
                            interdistrict,
                            os.path.join(curr_dir, dir, ""),
                        )
                    )

            except Exception as e:
                print(f"Exception {state}, {district_id}, {e}")
                pass
            # break

    # print(all_jobs[0])
    # produce_post_solver_files(*all_jobs[0])
    # exit()
    print("Starting parallel processing ...")
    from multiprocessing import Pool

    N_THREADS = 10
    p = Pool(N_THREADS)
    p.starmap(produce_post_solver_files, all_jobs)

    p.terminate()
    p.join()


def consolidate_results_files(
    batch="min_elem_4_interdistrict_bottom_sensitivity",
    batch_dir="data/results/{}",
    output_file="data/results/{}/consolidated_simulation_results_{}_{}_{}.csv",
):

    analytics_files = glob.glob(
        os.path.join(batch_dir.format(batch), "**/" + "analytics.csv"), recursive=True
    )
    all_dfs = []
    results_folder = []
    for i, f in enumerate(analytics_files):
        all_dfs.append(pd.read_csv(f, dtype={"NCESSCH": str, "district_id": str}))
        results_folder.append(f.split("/")[-2])

    df = pd.concat(all_dfs)
    df["results_folder"] = results_folder
    df_f = df.drop_duplicates(
        subset=["district_id", "school_decrease_threshold", "interdistrict"]
    )
    df_duplicates = df[
        ~df["results_folder"].isin(df_f["results_folder"].tolist())
    ].reset_index(drop=True)

    # print(df_duplicates.head(20))
    print("Num duplicates: ", len(df_duplicates))
    # exit()
    # Delete duplicate results' folders
    for i in range(0, len(df_duplicates)):
        shutil.rmtree(
            os.path.join(
                batch_dir.format(batch),
                df_duplicates["state"][i],
                df_duplicates["district_id"][i],
                df_duplicates["results_folder"][i],
            )
        )
    print("Num results: ", len(df_f))

    # Create different files for diff interdistrict, bottom constraint unique combos
    df_param_combos = df_f.groupby(
        ["school_decrease_threshold", "interdistrict"], as_index=False
    ).agg({"state": "count"})
    for i in range(0, len(df_param_combos)):
        school_decrease_threshold = df_param_combos["school_decrease_threshold"][i]
        interdistrict = df_param_combos["interdistrict"][i]
        df_curr = df_f[
            (df_f["school_decrease_threshold"] == school_decrease_threshold)
            & (df_f["interdistrict"] == interdistrict)
        ].reset_index(drop=True)
        df_curr.to_csv(
            output_file.format(batch, batch, school_decrease_threshold, interdistrict),
            index=False,
        )


def compare_batch_totals(
    batch_1="min_num_elem_schools_4_constrained",
    batch_2="min_num_elem_schools_4_bottomless",
    file_root="data/results/{}/consolidated_simulation_results_{}.csv",
):
    df_1 = pd.read_csv(file_root.format(batch_1, batch_1), dtype={"district_id": str})[
        ["district_id", "num_total_all"]
    ]
    df_2 = pd.read_csv(file_root.format(batch_2, batch_2), dtype={"district_id": str})[
        ["district_id", "num_total_all"]
    ].rename(columns={"num_total_all": "num_total_all_2"})
    df = pd.merge(df_1, df_2, on="district_id", how="inner")
    df["diff_totals"] = df["num_total_all"] != df["num_total_all_2"]
    print(df["diff_totals"].sum())
    df_diff = df[df["diff_totals"] == True].reset_index(drop=True)
    print(len(df_diff) / len(df))
    print(df_diff.head(10))


if __name__ == "__main__":
    produce_post_solver_files_parallel()
    consolidate_results_files()
    # compare_batch_totals()

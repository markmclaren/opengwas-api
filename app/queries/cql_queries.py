from resources._neo4j import Neo4j
from queries.user_node import User
from queries.gwas_info_node import GwasInfo
from queries.added_by_rel import AddedByRel
from queries.quality_control_rel import QualityControlRel
from queries.access_to_rel import AccessToRel
from queries.member_of_rel import MemberOfRel
from queries.group_node import Group
from schemas.gwas_info_node_schema import GwasInfoNodeSchema
import time
import os

"""Return all available GWAS summary datasets"""


def get_all_gwas_for_user(uid):
    gids = get_groups_for_user(uid)
    res = []
    tx = Neo4j.get_db()
    results = tx.run(
        "MATCH (g:Group)-[:ACCESS_TO]->(gi:GwasInfo)-[:DID_QC {data_passed:True}]->(:User) WHERE g.gid IN {gids} RETURN distinct(gi) as gi;",
        gids=list(gids)
    )
    for result in results:
        res.append(GwasInfo(result['gi']))

    return res


def get_all_gwas_ids_for_user(uid):
    recs = []
    gids = get_groups_for_user(uid)

    tx = Neo4j.get_db()
    results = tx.run(
        "MATCH (g:Group)-[:ACCESS_TO]->(gi:GwasInfo)-[:DID_QC {data_passed:True}]->(:User) WHERE g.gid IN {gids} RETURN distinct(gi.id) as id;",
        gids=list(gids)
    )

    for result in results:
        recs.append(result['id'])

    return recs


def get_gwas_for_user(uid, gwasid):
    gids = get_groups_for_user(uid)
    schema = GwasInfoNodeSchema()

    tx = Neo4j.get_db()

    results = tx.run(
        "MATCH (g:Group)-[:ACCESS_TO]->(gi:GwasInfo {id:{gwasid}})-[:DID_QC {data_passed:True}]->(:User) WHERE g.gid IN {gids} RETURN distinct(gi);",
        gids=list(gids),
        gwasid=gwasid
    )

    result = results.single()
    if result is None:
        raise LookupError("GwasInfo ID {} does not exist or you do not have the required access".format(gwasid))

    return schema.load(GwasInfo(result['gi']))


def add_new_gwas(user_email, gwas_info_dict, group_names=frozenset(['public'])):
    # get new id
    gwas_info_dict['id'] = str(GwasInfo.get_next_numeric_id())
    gwas_info_dict['priority'] = 0

    # populate nodes
    gwas_info_node = GwasInfo(gwas_info_dict)
    added_by_rel = AddedByRel({'epoch': time.time()})
    access_to_rel = AccessToRel()

    # persist or update
    gwas_info_node.create_node()
    added_by_rel.create_rel(gwas_info_node, User.get_node(user_email))

    # add grps
    for group_name in group_names:
        group_node = Group.get_node(group_name)
        access_to_rel.create_rel(group_node, gwas_info_node)

    return gwas_info_dict['id']


def add_new_user(email, group_names=frozenset(['public'])):
    member_of_rel = MemberOfRel()
    u = User(uid=email.strip().lower())
    u.create_node()

    for group_name in group_names:
        g = Group.get_node(group_name)
        member_of_rel.create_rel(u, g)


def add_group_to_user(email, group_name):
    member_of_rel = MemberOfRel()
    u = User.get_node(email)
    g = Group.get_node(group_name)
    member_of_rel.create_rel(u, g)


def update_filename_and_path(uid, full_remote_file_path, md5):
    if not os.path.exists(full_remote_file_path):
        raise FileNotFoundError("The GWAS file does not exist on this server: {}".format(full_remote_file_path))

    tx = Neo4j.get_db()
    tx.run(
        "MATCH (gi:GwasInfo {id:{uid}}) SET gi.filename={filename}, gi.path={path}, gi.md5={md5};",
        uid=uid,
        path=os.path.dirname(full_remote_file_path),
        filename=os.path.basename(full_remote_file_path),
        md5=md5
    )


def delete_gwas(gwasid):
    tx = Neo4j.get_db()
    tx.run(
        "MATCH (gi:GwasInfo {id:{gwasid}}) "
        "OPTIONAL MATCH (gi)-[rel]-() "
        "DELETE rel, gi;",
        gwasid=gwasid
    )


""" Returns studies for a list of study identifiers (or all public if keyword 'snp_lookup' provided)  """


# TODO do not show private data

def study_info(study_list):
    res = []
    schema = GwasInfoNodeSchema()
    tx = Neo4j.get_db()

    if study_list == 'snp_lookup':
        results = tx.run(
            "MATCH (:Group {gid:{gid}})-[:ACCESS_TO]->(gi:GwasInfo)-[:DID_QC {data_passed:True}]->(:User) RETURN gi;",
            gid=int(1)
        )
        for result in results:
            res.append(schema.load(result['gi']))

        return res
    else:
        study_list_str = []
        for s in study_list:
            study_list_str.append(str(s))

        results = tx.run(
            "MATCH (gi:GwasInfo)-[:DID_QC {data_passed:True}]->(:User) WHERE gi.id IN {study_list} RETURN gi;",
            study_list=study_list_str
        )
        for result in results:
            res.append(schema.load(result['gi']))

        return res


""" Returns list of group identifiers for a given user email (will accept NULL) """


def get_groups_for_user(uid):
    names = set()
    tx = Neo4j.get_db()
    results = tx.run(
        "MATCH (:User {uid:{uid}})-[:MEMBER_OF]->(g:Group) RETURN g.name as name;",
        uid=str(uid)
    )
    for result in results:
        names.add(result['name'])

    results = tx.run(
        "MATCH (g:Group {name:{name}}) RETURN g.gid as gid;",
        name=str('public')
    )
    for result in results:
        names.add(result['name'])

    return names


def get_permitted_studies(uid, sid):
    schema = GwasInfoNodeSchema()
    group_names = get_groups_for_user(uid)
    tx = Neo4j.get_db()
    results = tx.run(
        "MATCH (g:Group)-[:ACCESS_TO]->(s:GwasInfo)-[:DID_QC {data_passed:True}]->(:User) WHERE g.name IN {group_names} AND s.id IN {sid} RETURN distinct(s) as s;",
        group_names=list(group_names), sid=list(sid)
    )
    res = []
    for result in results:
        res.append(schema.load(result['s']))
    return res


def add_quality_control(user_email, gwas_info_id, data_passed, comment=None):
    u = User.get_node(user_email)
    g = GwasInfo.get_node(gwas_info_id)
    r = QualityControlRel(epoch=time.time(), data_passed=data_passed, comment=comment)

    # create QC rel
    r.create_rel(g, u)


def delete_quality_control(gwas_info_id):
    tx = Neo4j.get_db()
    tx.run(
        "MATCH (gi:GwasInfo {id:{uid}})-[r:DID_QC]->(:User) DELETE r;",
        uid=str(gwas_info_id)
    )


def check_user_is_admin(uid):
    try:
        u = User.get_node(uid)
    except LookupError:
        raise PermissionError("The token must resolve to a valid user")
    if 'admin' not in u:
        raise PermissionError("You must be an admin to complete this function")
    if not ['admin']:
        raise PermissionError("You must be an admin to complete this function")


def get_todo_quality_control():
    res = []
    tx = Neo4j.get_db()
    results = tx.run(
        "MATCH (gi:GwasInfo) WHERE NOT (gi)-[:DID_QC]->(:User) RETURN gi;"
    )
    for result in results:
        res.append(GwasInfo(result['gi']))

    return res
